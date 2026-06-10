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

import inspect
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth import CurrentUser, get_current_user
from api.db import get_current_household_id, service_tx, user_tx

log = logging.getLogger("pending_actions")

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
    from api.profile import load_profile
    from api.recipe_gen import generate_recipe

    prompt = p["prompt"]
    servings = int(p.get("servings", 4))
    # Feed the household's allergies/dislikes into generation so a fresh recipe
    # never contains them (the model also handles non-English terms by meaning).
    profile = await load_profile(await _resolve_household_id(user))
    try:
        gen = await generate_recipe(
            prompt, allergies=profile.allergies, dislikes=profile.dislikes
        )
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
        # LLMs occasionally repeat the same fdc_id under two ingredient names
        # and occasionally hallucinate fdc_ids that aren't in USDA. Dedup,
        # then drop hallucinated ones — the FK would otherwise abort the
        # whole save.
        grams_by_fdc: dict[int, float] = {}
        for ing in gen.ingredients:
            grams_by_fdc[ing.fdc_id] = grams_by_fdc.get(ing.fdc_id, 0.0) + ing.quantity_g
        if grams_by_fdc:
            valid_rows = await conn.fetch(
                "SELECT fdc_id FROM hearth.usda_ingredients "
                "WHERE fdc_id = ANY($1::int[])",
                list(grams_by_fdc.keys()),
            )
            valid_set = {r["fdc_id"] for r in valid_rows}
            dropped = [fid for fid in grams_by_fdc if fid not in valid_set]
            if dropped:
                log.warning("[recipe.create] dropped hallucinated fdc_ids: %s", dropped)
            for fdc_id, qty in grams_by_fdc.items():
                if fdc_id not in valid_set:
                    continue
                await conn.execute(
                    "INSERT INTO hearth.recipe_ingredients (recipe_id, fdc_id, quantity_g) "
                    "VALUES ($1::uuid, $2, $3)",
                    recipe_id, fdc_id, qty,
                )

    # Mirror into the public pool so other households can discover this recipe
    # via Explore. Auto-share is the project's chosen default. Failures here
    # never block the user's save.
    from api.image_gen import schedule_pool_image
    from api.public_pool import mirror_to_pool
    public_id = await mirror_to_pool(
        name=gen.name,
        ingredients=[{"fdc_id": i.fdc_id, "name": i.name, "quantity_g": i.quantity_g}
                     for i in gen.ingredients],
        instructions=gen.instructions,
        source="llm",
        originating_household_id=household_id,
    )
    # Link the personal copy to its pool origin so the eventual pool image
    # back-fills here too. No duplicate image gen needed.
    if public_id:
        # New pool entry — link the personal copy to it and let the pool
        # image generation back-fill image_path on this row when done.
        async with user_tx(user) as conn:
            await conn.execute(
                "UPDATE hearth.recipes SET public_origin_id = $1::uuid "
                "WHERE id = $2::uuid",
                public_id, recipe_id,
            )
        schedule_pool_image(public_id, gen.name)
    else:
        # Name already in pool — inherit its image (if any) and link.
        async with service_tx() as conn:
            pool_row = await conn.fetchrow(
                "SELECT id::text AS id, image_path FROM hearth.public_recipes "
                "WHERE lower(name) = lower($1)",
                gen.name,
            )
        if pool_row:
            async with user_tx(user) as conn:
                await conn.execute(
                    "UPDATE hearth.recipes SET public_origin_id = $1::uuid, "
                    "image_path = COALESCE(image_path, $2) WHERE id = $3::uuid",
                    pool_row["id"], pool_row["image_path"], recipe_id,
                )
        if not pool_row or not pool_row["image_path"]:
            # No pool image to inherit — give the user a personal one.
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
            household_id, p["name"], date.fromisoformat(p["start_date"]),
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
    """Legacy alias for calendar.add_meal — keeps any in-flight `plan.add_entry`
    pending actions working without crashing on the household_id NOT NULL
    constraint. We ignore the plan_id from the params; meals are calendar-flat now."""
    return await _exec_calendar_add_meal(user, p)


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


async def _exec_profile_field(user: CurrentUser, p: dict, locale: str = "en") -> ExecResult:
    from api.profile import (
        ADDITIVE_LIST_FIELDS,
        HouseholdProfile,
        _save_profile,
        apply_field_mode,
        coerce_profile_value,
        describe_profile_result,
        load_profile,
    )
    # household_id from the user (via the JWT-derived membership table)
    household_id = await _resolve_household_id(user)
    field = p["field"]
    value = p["value"]
    # Legacy proposals (queued before modes existed) carry no mode → 'set', the
    # old behaviour. New ones default to 'add' for additive list fields.
    mode = str(p.get("mode", "set")).lower()
    try:
        coerced = coerce_profile_value(field, value)
    except ValueError as e:
        return str(e), {}
    current = await load_profile(household_id)
    data = current.model_dump(exclude={"updated_at"})
    if field in ADDITIVE_LIST_FIELDS:
        data[field] = apply_field_mode(field, data.get(field), coerced, mode)
    else:
        data[field] = coerced
    await _save_profile(household_id, HouseholdProfile(**data))
    return describe_profile_result(field, data[field], locale), {}


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


async def _exec_calendar_add_meal(user: CurrentUser, p: dict) -> ExecResult:
    """Drop a meal directly onto the household calendar — no plan wrapper.
    The chat agent's `propose_add_meal_to_calendar` uses this; old
    `plan.add_entry` still works for legacy proposals."""
    household_id = await _household_for(user)
    if household_id is None:
        return "Could not determine household.", {}

    async with user_tx(user) as conn:
        recipe = await conn.fetchrow(
            "SELECT name FROM hearth.recipes WHERE id = $1::uuid",
            p["recipe_id"],
        )
        if recipe is None:
            return f"Recipe {p['recipe_id']} no longer exists.", {}
        plan_date = date.fromisoformat(p["plan_date"])
        slot = p.get("slot", "dinner")
        portions = max(0.25, float(p.get("portions", 1)))
        entry = await conn.fetchrow(
            """
            INSERT INTO hearth.meal_plan_entries
                (household_id, recipe_id, plan_date, slot, portions)
            VALUES ($1::uuid, $2::uuid, $3::date, $4, $5)
            RETURNING id::text AS id
            """,
            household_id, p["recipe_id"], plan_date, slot, portions,
        )
    return (
        f"Added '{recipe['name']}' to the calendar on {p['plan_date']} ({slot}).",
        {
            "entry_id": entry["id"],
            "recipe_id": p["recipe_id"],
            "plan_date": p["plan_date"],
        },
    )


async def _exec_pantry_add(user: CurrentUser, p: dict) -> ExecResult:
    household_id = await _household_for(user)
    if household_id is None:
        return "Could not determine household.", {}
    async with user_tx(user) as conn:
        row = await conn.fetchrow(
            "SELECT description FROM hearth.usda_ingredients WHERE fdc_id = $1",
            int(p["fdc_id"]),
        )
        if row is None:
            return f"fdc_id={p['fdc_id']} not in USDA catalogue.", {}
        await conn.execute(
            """
            INSERT INTO hearth.household_staples (household_id, fdc_id)
            VALUES ($1::uuid, $2)
            ON CONFLICT DO NOTHING
            """,
            household_id, int(p["fdc_id"]),
        )
    return f"Added '{row['description']}' to the pantry.", {"fdc_id": int(p["fdc_id"])}


async def _exec_pantry_remove(user: CurrentUser, p: dict) -> ExecResult:
    household_id = await _household_for(user)
    if household_id is None:
        return "Could not determine household.", {}
    async with user_tx(user) as conn:
        row = await conn.fetchrow(
            "SELECT description FROM hearth.usda_ingredients WHERE fdc_id = $1",
            int(p["fdc_id"]),
        )
        if row is None:
            return f"fdc_id={p['fdc_id']} not in USDA catalogue.", {}
        await conn.execute(
            "DELETE FROM hearth.household_staples "
            "WHERE household_id = $1::uuid AND fdc_id = $2",
            household_id, int(p["fdc_id"]),
        )
    return f"Removed '{row['description']}' from the pantry.", {"fdc_id": int(p["fdc_id"])}


async def _exec_recipe_import_from_pool(user: CurrentUser, p: dict) -> ExecResult:
    """Copy a row from hearth.public_recipes into the household's saved
    recipes. Free, instant, no LLM credit. Idempotent — re-importing the
    same pool entry just returns the existing recipe_id."""
    from api.public_pool import copy_to_household

    household_id = await _household_for(user)
    if household_id is None:
        return "Could not determine household.", {}

    recipe_id, recipe_name = await copy_to_household(p["public_recipe_id"], household_id)
    if recipe_id is None:
        return f"Pool recipe {p['public_recipe_id']} not found.", {}
    return (
        f"Imported '{recipe_name}' from the recipe library.",
        {"recipe_id": recipe_id, "name": recipe_name},
    )


async def _household_for(user: CurrentUser) -> str | None:
    async with user_tx(user) as conn:
        return await conn.fetchval(
            "SELECT household_id::text FROM public.household_members "
            "WHERE user_id = $1::uuid LIMIT 1",
            user.user_id,
        )


_EXECUTORS = {
    "recipe.rename":            _exec_recipe_rename,
    "recipe.servings":          _exec_recipe_servings,
    "recipe.delete":            _exec_recipe_delete,
    "recipe.create":            _exec_recipe_create,
    "recipe.import_from_pool":  _exec_recipe_import_from_pool,
    # plan.create / plan.delete kept registered so in-flight pending cards
    # can still resolve, but the agent can no longer propose them.
    "plan.create":              _exec_plan_create,
    "plan.delete":              _exec_plan_delete,
    "plan.add_entry":           _exec_plan_add_entry,        # legacy alias for calendar.add_meal
    "plan.remove_entry":        _exec_plan_remove_entry,     # legacy alias for calendar.remove_meal
    "plan.update_portions":     _exec_plan_update_portions,  # legacy alias for calendar.update_portions
    "calendar.add_meal":        _exec_calendar_add_meal,
    "calendar.remove_meal":     _exec_plan_remove_entry,
    "calendar.update_portions": _exec_plan_update_portions,
    "profile.field":            _exec_profile_field,
    "profile.note":             _exec_profile_note,
    "pantry.add":               _exec_pantry_add,
    "pantry.remove":            _exec_pantry_remove,
}


async def execute(kind: str, user: CurrentUser, params: dict, locale: str = "en") -> ExecResult:
    fn = _EXECUTORS.get(kind)
    if not fn:
        return f"Unknown action kind '{kind}'.", {}
    # Only executors that render a user-facing result (profile.*) take a locale;
    # the rest keep their (user, params) signature.
    if "locale" in inspect.signature(fn).parameters:
        return await fn(user, params, locale=locale)
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
    locale: str = Query("en"),
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
        result, created = await execute(p["kind"], user, params, locale)
        status = "accepted"
    except Exception as e:
        log.exception("[pending] execute(%s) failed for pid=%s", p["kind"], pid)
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
