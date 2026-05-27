"""Human-in-the-loop write pipeline for the chat agent (Postgres-backed).

Flow:
1. The agent's *mutating* tools call `PendingProposer.propose(kind, summary, params)`
   instead of writing. The proposer buffers proposals.
2. At end of turn, the chat endpoint calls `proposer.flush()` which persists
   them to `hearth.pending_actions` (RLS-scoped via user_tx) and returns the
   rows to surface in the response.
3. The UI renders Accept / Reject buttons per pending card.
4. Accept -> `POST /chat/pending/{id}/accept` -> `execute(...)` dispatches to a
   per-kind executor, status flips to 'accepted'/'failed'.
5. Reject -> `POST /chat/pending/{id}/reject` -> status='rejected'.

Read-only tools (list/get/search) run inline; they don't need approval.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import CurrentUser, get_current_user
from api.db import get_current_household_id, user_tx

router = APIRouter(prefix="/chat/pending", tags=["chat"])


# ============================================================
# Proposer (used by agent_tools)
# ============================================================


class PendingProposer:
    """Tools call this during an agent turn. It buffers proposals to be
    persisted at the end of the turn by the chat endpoint."""

    def __init__(self, session_id: str, household_id: str, user: CurrentUser):
        self.session_id = session_id
        self.household_id = household_id
        self.user = user
        self._buffered: list[dict] = []

    def propose(self, kind: str, summary: str, params: dict) -> str:
        """Queue a pending action. Returns a placeholder id used by the tool's
        return string. The DB-assigned UUID overwrites it on flush()."""
        # A real DB-assigned id is produced on flush; use a deterministic
        # placeholder so the tool's reply string is stable for this turn.
        placeholder = f"pending-{len(self._buffered)}"
        self._buffered.append({
            "id": placeholder, "kind": kind, "summary": summary, "params": params,
        })
        return placeholder

    async def flush(self) -> list[dict]:
        """Persist and return the buffered proposals with their DB-assigned ids."""
        if not self._buffered:
            return []
        async with user_tx(self.user) as conn:
            for p in self._buffered:
                row = await conn.fetchrow(
                    """
                    INSERT INTO hearth.pending_actions
                        (session_id, household_id, kind, summary, params, status)
                    VALUES ($1::uuid, $2::uuid, $3, $4, $5::jsonb, 'pending')
                    RETURNING id::text AS id
                    """,
                    self.session_id, self.household_id,
                    p["kind"], p["summary"], p["params"],
                )
                p["id"] = row["id"]
        out = list(self._buffered)
        self._buffered.clear()
        return out


# ============================================================
# Wire models
# ============================================================


class PendingActionOut(BaseModel):
    id: str
    kind: str
    summary: str
    params: dict
    status: str
    result: str | None = None
    created_at: str
    resolved_at: str | None = None


class ResolveResponse(BaseModel):
    id: str
    status: str
    result: str | None
    created: dict[str, str] | None


# ============================================================
# Executors
# ============================================================


ExecResult = tuple[str, dict[str, str]]


async def _exec_recipe_rename(user: CurrentUser, p: dict) -> ExecResult:
    recipe_id = p["recipe_id"]
    new_name = p["new_name"]
    async with user_tx(user) as conn:
        row = await conn.fetchrow(
            "SELECT name FROM hearth.recipes WHERE id = $1::uuid",
            recipe_id,
        )
        if row is None:
            return f"Recipe {recipe_id} no longer exists.", {}
        old = row["name"]
        await conn.execute(
            "UPDATE hearth.recipes SET name = $1, updated_at = now() WHERE id = $2::uuid",
            new_name, recipe_id,
        )
    return f"Renamed '{old}' -> '{new_name}'.", {"recipe_id": recipe_id}


async def _exec_recipe_servings(user: CurrentUser, p: dict) -> ExecResult:
    recipe_id = p["recipe_id"]
    servings = max(1, int(p["servings"]))
    async with user_tx(user) as conn:
        row = await conn.fetchrow(
            "SELECT name FROM hearth.recipes WHERE id = $1::uuid",
            recipe_id,
        )
        if row is None:
            return f"Recipe {recipe_id} no longer exists.", {}
        await conn.execute(
            "UPDATE hearth.recipes SET servings = $1, updated_at = now() WHERE id = $2::uuid",
            servings, recipe_id,
        )
    return f"Set '{row['name']}' to {servings} servings.", {"recipe_id": recipe_id}


async def _exec_recipe_delete(user: CurrentUser, p: dict) -> ExecResult:
    recipe_id = p["recipe_id"]
    async with user_tx(user) as conn:
        row = await conn.fetchrow(
            "SELECT name FROM hearth.recipes WHERE id = $1::uuid",
            recipe_id,
        )
        if row is None:
            return f"Recipe {recipe_id} no longer exists.", {}
        await conn.execute(
            "DELETE FROM hearth.recipes WHERE id = $1::uuid",
            recipe_id,
        )
    return f"Deleted recipe '{row['name']}'.", {}


async def _exec_recipe_create(user: CurrentUser, p: dict) -> ExecResult:
    """Generate + save a recipe on accept. Defers token spend until the user agrees."""
    from api.image_gen import schedule_image
    from api.recipe_gen import generate_recipe

    prompt = p["prompt"]
    servings = int(p.get("servings", 4))
    try:
        gen = await generate_recipe(prompt)
    except Exception as e:
        return f"Generation failed: {e}", {}

    async with user_tx(user) as conn:
        # household_id comes from the JWT — RLS WITH CHECK validates membership.
        household_id = await conn.fetchval(
            "SELECT household_id::text FROM public.household_members "
            "WHERE user_id = $1::uuid LIMIT 1",
            user.user_id,
        )
        recipe_row = await conn.fetchrow(
            """
            INSERT INTO hearth.recipes (household_id, name, instructions, servings)
            VALUES ($1::uuid, $2, $3::jsonb, $4)
            RETURNING id::text AS id
            """,
            household_id, gen.name, gen.instructions, servings,
        )
        recipe_id = recipe_row["id"]
        for ing in gen.ingredients:
            await conn.execute(
                "INSERT INTO hearth.recipe_ingredients (recipe_id, fdc_id, quantity_g) "
                "VALUES ($1::uuid, $2, $3)",
                recipe_id, ing.fdc_id, ing.quantity_g,
            )

    schedule_image(recipe_id, gen.name, household_id)
    return (
        f"Created '{gen.name}' with {len(gen.ingredients)} ingredients "
        f"and {len(gen.instructions)} steps.",
        {"recipe_id": recipe_id},
    )


async def _exec_plan_create(user: CurrentUser, p: dict) -> ExecResult:
    async with user_tx(user) as conn:
        household_id = await conn.fetchval(
            "SELECT household_id::text FROM public.household_members "
            "WHERE user_id = $1::uuid LIMIT 1",
            user.user_id,
        )
        row = await conn.fetchrow(
            """
            INSERT INTO hearth.meal_plans (household_id, name, start_date)
            VALUES ($1::uuid, $2, $3::date)
            RETURNING id::text AS id
            """,
            household_id, p["name"], p["start_date"],
        )
    return f"Created meal plan '{p['name']}'.", {"plan_id": row["id"]}


async def _exec_plan_delete(user: CurrentUser, p: dict) -> ExecResult:
    plan_id = p["plan_id"]
    async with user_tx(user) as conn:
        row = await conn.fetchrow(
            "SELECT name FROM hearth.meal_plans WHERE id = $1::uuid",
            plan_id,
        )
        if row is None:
            return f"Plan {plan_id} no longer exists.", {}
        await conn.execute(
            "DELETE FROM hearth.meal_plans WHERE id = $1::uuid",
            plan_id,
        )
    return f"Deleted meal plan '{row['name']}'.", {}


async def _exec_plan_add_entry(user: CurrentUser, p: dict) -> ExecResult:
    async with user_tx(user) as conn:
        plan = await conn.fetchrow(
            "SELECT name FROM hearth.meal_plans WHERE id = $1::uuid",
            p["plan_id"],
        )
        if plan is None:
            return f"Plan {p['plan_id']} no longer exists.", {}
        recipe = await conn.fetchrow(
            "SELECT name FROM hearth.recipes WHERE id = $1::uuid",
            p["recipe_id"],
        )
        if recipe is None:
            return f"Recipe {p['recipe_id']} no longer exists.", {}
        entry_row = await conn.fetchrow(
            """
            INSERT INTO hearth.meal_plan_entries
                (meal_plan_id, recipe_id, plan_date, slot, portions)
            VALUES ($1::uuid, $2::uuid, $3::date, $4, $5)
            RETURNING id::text AS id
            """,
            p["plan_id"], p["recipe_id"], p["plan_date"],
            p.get("slot", "dinner"), float(p.get("portions", 1)),
        )
        await conn.execute(
            "UPDATE hearth.meal_plans SET updated_at = now() WHERE id = $1::uuid",
            p["plan_id"],
        )
    return (
        f"Added '{recipe['name']}' to '{plan['name']}' on "
        f"{p['plan_date']} ({p.get('slot', 'dinner')}).",
        {"plan_id": p["plan_id"], "entry_id": entry_row["id"], "recipe_id": p["recipe_id"]},
    )


async def _exec_plan_remove_entry(user: CurrentUser, p: dict) -> ExecResult:
    entry_id = p["entry_id"]
    async with user_tx(user) as conn:
        row = await conn.fetchrow(
            """
            SELECT e.plan_date, e.slot, r.name AS recipe_name
            FROM hearth.meal_plan_entries e
            LEFT JOIN hearth.recipes r ON r.id = e.recipe_id
            WHERE e.id = $1::uuid
            """,
            entry_id,
        )
        if row is None:
            return f"Entry {entry_id} no longer exists.", {}
        await conn.execute(
            "DELETE FROM hearth.meal_plan_entries WHERE id = $1::uuid",
            entry_id,
        )
    return (
        f"Removed '{row['recipe_name']}' from "
        f"{row['plan_date'].isoformat() if row['plan_date'] else ''} {row['slot']}.",
        {},
    )


async def _exec_plan_update_portions(user: CurrentUser, p: dict) -> ExecResult:
    entry_id = p["entry_id"]
    portions = max(0.25, float(p["portions"]))
    async with user_tx(user) as conn:
        row = await conn.fetchrow(
            """
            SELECT r.name AS recipe_name, e.meal_plan_id::text AS meal_plan_id
            FROM hearth.meal_plan_entries e
            LEFT JOIN hearth.recipes r ON r.id = e.recipe_id
            WHERE e.id = $1::uuid
            """,
            entry_id,
        )
        if row is None:
            return f"Entry {entry_id} no longer exists.", {}
        await conn.execute(
            "UPDATE hearth.meal_plan_entries SET portions = $1 WHERE id = $2::uuid",
            portions, entry_id,
        )
    return (
        f"Set portions for '{row['recipe_name']}' to {portions}.",
        {"entry_id": entry_id, "plan_id": row["meal_plan_id"]},
    )


async def _exec_profile_field(user: CurrentUser, p: dict) -> ExecResult:
    from api.profile import (
        HouseholdProfile,
        _save_profile,
        coerce_profile_value,
        load_profile,
    )
    # household_id from the user (via the JWT-derived membership table)
    household_id = await _resolve_household_id(user)
    field = p["field"]
    value = p["value"]
    try:
        coerced = coerce_profile_value(field, value)
    except ValueError as e:
        return str(e), {}
    current = await load_profile(household_id)
    data = current.model_dump(exclude={"updated_at"})
    data[field] = coerced
    await _save_profile(household_id, HouseholdProfile(**data))
    return f"Set profile.{field} to {coerced}.", {}


async def _exec_profile_note(user: CurrentUser, p: dict) -> ExecResult:
    from api.profile import HouseholdProfile, _save_profile, load_profile

    household_id = await _resolve_household_id(user)
    note = str(p["note"]).strip()
    if not note:
        return "Empty note discarded.", {}
    current = await load_profile(household_id)
    data = current.model_dump(exclude={"updated_at"})
    notes = list(data.get("notes", []))
    notes.append(note)
    data["notes"] = notes
    await _save_profile(household_id, HouseholdProfile(**data))
    return f"Recorded note: {note}", {}


async def _resolve_household_id(user: CurrentUser) -> str:
    """Service-role lookup of the user's household_id.
    Used by executors that mutate via service_tx-flavoured helpers."""
    from api.db import service_tx
    async with service_tx() as conn:
        return await conn.fetchval(
            "SELECT household_id::text FROM public.household_members "
            "WHERE user_id = $1::uuid LIMIT 1",
            user.user_id,
        )


_EXECUTORS = {
    "recipe.rename":         _exec_recipe_rename,
    "recipe.servings":       _exec_recipe_servings,
    "recipe.delete":         _exec_recipe_delete,
    "recipe.create":         _exec_recipe_create,
    "plan.create":           _exec_plan_create,
    "plan.delete":           _exec_plan_delete,
    "plan.add_entry":        _exec_plan_add_entry,
    "plan.remove_entry":     _exec_plan_remove_entry,
    "plan.update_portions":  _exec_plan_update_portions,
    "profile.field":         _exec_profile_field,
    "profile.note":          _exec_profile_note,
}


async def execute(kind: str, user: CurrentUser, params: dict) -> ExecResult:
    fn = _EXECUTORS.get(kind)
    if not fn:
        return f"Unknown action kind '{kind}'.", {}
    return await fn(user, params)


# ============================================================
# Endpoints
# ============================================================


async def _load_pending(user: CurrentUser, pid: str) -> dict | None:
    async with user_tx(user) as conn:
        row = await conn.fetchrow(
            """
            SELECT id::text AS id, session_id::text AS session_id,
                   household_id::text AS household_id,
                   kind, summary, params, status, result, created_at, resolved_at
            FROM hearth.pending_actions WHERE id = $1::uuid
            """,
            pid,
        )
    return dict(row) if row else None


@router.post("/{pid}/accept", response_model=ResolveResponse)
async def accept_pending(
    pid: str,
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    p = await _load_pending(user, pid)
    if not p:
        raise HTTPException(404, "Pending action not found")
    if p["household_id"] != household_id:
        raise HTTPException(403, "Pending action belongs to a different household")
    if p["status"] != "pending":
        raise HTTPException(409, f"Already {p['status']}")

    params = p["params"] if isinstance(p["params"], dict) else {}

    created: dict[str, str] = {}
    try:
        result, created = await execute(p["kind"], user, params)
        status = "accepted"
    except Exception as e:
        result = f"Execution failed: {e}"
        status = "failed"

    async with user_tx(user) as conn:
        await conn.execute(
            """
            UPDATE hearth.pending_actions
            SET status = $1, result = $2, resolved_at = now()
            WHERE id = $3::uuid
            """,
            status, result, pid,
        )
    return ResolveResponse(
        id=pid, status=status, result=result, created=created or None,
    )


@router.post("/{pid}/reject", response_model=ResolveResponse)
async def reject_pending(
    pid: str,
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    p = await _load_pending(user, pid)
    if not p:
        raise HTTPException(404, "Pending action not found")
    if p["household_id"] != household_id:
        raise HTTPException(403, "Pending action belongs to a different household")
    if p["status"] != "pending":
        raise HTTPException(409, f"Already {p['status']}")
    async with user_tx(user) as conn:
        await conn.execute(
            """
            UPDATE hearth.pending_actions
            SET status = 'rejected', resolved_at = now()
            WHERE id = $1::uuid
            """,
            pid,
        )
    return ResolveResponse(id=pid, status="rejected", result=None, created=None)


@router.get("/sessions/{sid}", response_model=list[PendingActionOut])
async def list_pending_for_session(
    sid: str,
    only_pending: bool = False,
    user: CurrentUser = Depends(get_current_user),
):
    """List proposals for a session. Used on chat reload so pending items persist
    across page refreshes."""
    sql = (
        "SELECT id::text AS id, kind, summary, params, status, result, "
        "       created_at, resolved_at "
        "FROM hearth.pending_actions WHERE session_id = $1::uuid"
    )
    if only_pending:
        sql += " AND status = 'pending'"
    sql += " ORDER BY created_at ASC"

    async with user_tx(user) as conn:
        rows = await conn.fetch(sql, sid)

    out: list[PendingActionOut] = []
    for r in rows:
        out.append(PendingActionOut(
            id=r["id"], kind=r["kind"], summary=r["summary"],
            params=r["params"] if isinstance(r["params"], dict) else {},
            status=r["status"], result=r["result"],
            created_at=r["created_at"].isoformat() if r["created_at"] else "",
            resolved_at=r["resolved_at"].isoformat() if r["resolved_at"] else None,
        ))
    return out
