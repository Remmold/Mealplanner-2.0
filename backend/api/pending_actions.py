"""Human-in-the-loop write pipeline for the chat agent.

Flow:
1. The agent's *mutating* tools call `PendingProposer.propose(kind, summary, params)`
   instead of writing to the DB. This records a row in `pending_actions` with
   status='pending' and returns the id so the tool's return string can reference
   it ("Proposed: create recipe (id=...); awaiting your approval").
2. The chat endpoint returns the new pending rows along with the assistant reply.
3. The UI renders Accept / Reject buttons per pending card.
4. Accept -> `POST /chat/pending/{id}/accept` -> dispatch to `_execute_<kind>`,
   mark row status='accepted', return the outcome.
5. Reject -> `POST /chat/pending/{id}/reject` -> just mark status='rejected'.

Read-only tools (list/get/search) still run inline; they don't need approval.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.recipe_db import DEFAULT_HOUSEHOLD_ID, get_recipe_db, new_id

router = APIRouter(prefix="/chat/pending", tags=["chat"])


# ============================================================
# Proposer (used by agent_tools)
# ============================================================


class PendingProposer:
    """Tools call this during an agent turn. It buffers proposals to be
    persisted at the end of the turn by the chat endpoint."""

    def __init__(self, session_id: str, household_id: str):
        self.session_id = session_id
        self.household_id = household_id
        self._buffered: list[dict] = []

    def propose(self, kind: str, summary: str, params: dict) -> str:
        """Queue a pending action. Returns the id that the UI will use for Accept/Reject."""
        pid = new_id()
        self._buffered.append({
            "id": pid, "kind": kind, "summary": summary,
            "params": params,
        })
        return pid

    def flush(self) -> list[dict]:
        """Persist and return the buffered proposals. Called at end of turn."""
        if not self._buffered:
            return []
        with get_recipe_db() as conn:
            for p in self._buffered:
                conn.execute(
                    "INSERT INTO pending_actions "
                    "(id, session_id, household_id, kind, summary, params, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'pending')",
                    [
                        p["id"], self.session_id, self.household_id,
                        p["kind"], p["summary"], json.dumps(p["params"]),
                    ],
                )
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
    status: str                       # 'accepted' | 'rejected' | 'failed'
    result: str | None                # human-readable outcome
    created: dict[str, str] | None    # {'recipe_id': ..., 'plan_id': ..., 'entry_id': ...}
                                      # so the UI can link to the new entity


# ============================================================
# Executors — one per kind. Each returns a human-readable outcome string.
# Any schema change to the app's write operations must be mirrored here.
# ============================================================


# Executors return a tuple: (human-readable summary, created_ids).
# `created_ids` is a dict like {'recipe_id': '...', 'plan_id': '...'}
# that the UI uses to show a clickable preview after acceptance.
ExecResult = tuple[str, dict[str, str]]


def _exec_recipe_rename(household_id: str, p: dict) -> ExecResult:
    recipe_id = p["recipe_id"]; new_name = p["new_name"]
    with get_recipe_db() as conn:
        row = conn.execute(
            "SELECT name FROM recipes WHERE id = ? AND household_id = ?",
            [recipe_id, household_id],
        ).fetchone()
        if not row:
            return f"Recipe {recipe_id} no longer exists.", {}
        old = row["name"]
        conn.execute(
            "UPDATE recipes SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [new_name, recipe_id],
        )
    return f"Renamed '{old}' -> '{new_name}'.", {"recipe_id": recipe_id}


def _exec_recipe_servings(household_id: str, p: dict) -> ExecResult:
    recipe_id = p["recipe_id"]; servings = max(1, int(p["servings"]))
    with get_recipe_db() as conn:
        row = conn.execute(
            "SELECT name FROM recipes WHERE id = ? AND household_id = ?",
            [recipe_id, household_id],
        ).fetchone()
        if not row:
            return f"Recipe {recipe_id} no longer exists.", {}
        conn.execute(
            "UPDATE recipes SET servings = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [servings, recipe_id],
        )
    return f"Set '{row['name']}' to {servings} servings.", {"recipe_id": recipe_id}


def _exec_recipe_delete(household_id: str, p: dict) -> ExecResult:
    recipe_id = p["recipe_id"]
    with get_recipe_db() as conn:
        row = conn.execute(
            "SELECT name FROM recipes WHERE id = ? AND household_id = ?",
            [recipe_id, household_id],
        ).fetchone()
        if not row:
            return f"Recipe {recipe_id} no longer exists.", {}
        conn.execute("DELETE FROM recipes WHERE id = ?", [recipe_id])
    return f"Deleted recipe '{row['name']}'.", {}


async def _exec_recipe_create(household_id: str, p: dict) -> ExecResult:
    """Actually generate + save a recipe on accept. This is the only executor
    that spends tokens; we defer the generation until the user has agreed."""
    from api.recipe_gen import generate_recipe
    prompt = p["prompt"]; servings = int(p.get("servings", 4))
    try:
        gen = await generate_recipe(prompt)
    except Exception as e:
        return f"Generation failed: {e}", {}
    recipe_id = new_id()
    with get_recipe_db() as conn:
        conn.execute(
            "INSERT INTO recipes (id, household_id, name, instructions, servings) "
            "VALUES (?, ?, ?, ?, ?)",
            [recipe_id, household_id, gen.name, json.dumps(gen.instructions), servings],
        )
        for ing in gen.ingredients:
            conn.execute(
                "INSERT INTO recipe_ingredients (id, recipe_id, fdc_id, quantity_g) "
                "VALUES (?, ?, ?, ?)",
                [new_id(), recipe_id, ing.fdc_id, ing.quantity_g],
            )
    from api.image_gen import schedule_image
    schedule_image(recipe_id, gen.name, household_id)
    return (
        f"Created '{gen.name}' with {len(gen.ingredients)} ingredients "
        f"and {len(gen.instructions)} steps.",
        {"recipe_id": recipe_id},
    )


def _exec_plan_create(household_id: str, p: dict) -> ExecResult:
    plan_id = new_id()
    with get_recipe_db() as conn:
        conn.execute(
            "INSERT INTO meal_plans (id, household_id, name, start_date) VALUES (?, ?, ?, ?)",
            [plan_id, household_id, p["name"], p["start_date"]],
        )
    return f"Created meal plan '{p['name']}'.", {"plan_id": plan_id}


def _exec_plan_delete(household_id: str, p: dict) -> ExecResult:
    plan_id = p["plan_id"]
    with get_recipe_db() as conn:
        row = conn.execute(
            "SELECT name FROM meal_plans WHERE id = ? AND household_id = ?",
            [plan_id, household_id],
        ).fetchone()
        if not row:
            return f"Plan {plan_id} no longer exists.", {}
        conn.execute("DELETE FROM meal_plans WHERE id = ?", [plan_id])
    return f"Deleted meal plan '{row['name']}'.", {}


def _exec_plan_add_entry(household_id: str, p: dict) -> ExecResult:
    with get_recipe_db() as conn:
        plan = conn.execute(
            "SELECT name FROM meal_plans WHERE id = ? AND household_id = ?",
            [p["plan_id"], household_id],
        ).fetchone()
        if not plan:
            return f"Plan {p['plan_id']} no longer exists.", {}
        recipe = conn.execute(
            "SELECT name FROM recipes WHERE id = ? AND household_id = ?",
            [p["recipe_id"], household_id],
        ).fetchone()
        if not recipe:
            return f"Recipe {p['recipe_id']} no longer exists.", {}
        entry_id = new_id()
        conn.execute(
            "INSERT INTO meal_plan_entries (id, meal_plan_id, recipe_id, plan_date, slot, portions) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [entry_id, p["plan_id"], p["recipe_id"], p["plan_date"],
             p.get("slot", "dinner"), float(p.get("portions", 1))],
        )
        conn.execute(
            "UPDATE meal_plans SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [p["plan_id"]],
        )
    return (
        f"Added '{recipe['name']}' to '{plan['name']}' on {p['plan_date']} ({p.get('slot', 'dinner')}).",
        {"plan_id": p["plan_id"], "entry_id": entry_id, "recipe_id": p["recipe_id"]},
    )


def _exec_plan_remove_entry(household_id: str, p: dict) -> ExecResult:
    entry_id = p["entry_id"]
    with get_recipe_db() as conn:
        row = conn.execute(
            "SELECT e.plan_date, e.slot, r.name AS recipe_name "
            "FROM meal_plan_entries e LEFT JOIN recipes r ON r.id = e.recipe_id "
            "WHERE e.id = ?",
            [entry_id],
        ).fetchone()
        if not row:
            return f"Entry {entry_id} no longer exists.", {}
        conn.execute("DELETE FROM meal_plan_entries WHERE id = ?", [entry_id])
    return f"Removed '{row['recipe_name']}' from {row['plan_date']} {row['slot']}.", {}


def _exec_plan_update_portions(household_id: str, p: dict) -> ExecResult:
    entry_id = p["entry_id"]; portions = max(0.25, float(p["portions"]))
    with get_recipe_db() as conn:
        row = conn.execute(
            "SELECT r.name AS recipe_name, e.meal_plan_id FROM meal_plan_entries e "
            "LEFT JOIN recipes r ON r.id = e.recipe_id WHERE e.id = ?",
            [entry_id],
        ).fetchone()
        if not row:
            return f"Entry {entry_id} no longer exists.", {}
        conn.execute("UPDATE meal_plan_entries SET portions = ? WHERE id = ?", [portions, entry_id])
    return (
        f"Set portions for '{row['recipe_name']}' to {portions}.",
        {"entry_id": entry_id, "plan_id": row["meal_plan_id"]},
    )


def _exec_profile_field(household_id: str, p: dict) -> ExecResult:
    from api.profile import load_profile, _save_profile, HouseholdProfile, PROFILE_FIELDS
    field = p["field"]; value = p["value"]
    if field not in PROFILE_FIELDS:
        return f"Unknown field '{field}'.", {}
    current = load_profile(household_id)
    data = current.model_dump(exclude={"updated_at"})
    list_fields = {"dietary", "allergies", "dislikes", "likes", "cuisines", "kitchen_equipment"}
    int_fields = {"family_size", "typical_cook_time_min"}
    if field in list_fields:
        data[field] = [s.strip() for s in str(value).split(",") if s.strip()]
    elif field in int_fields:
        data[field] = int(value)
    else:
        data[field] = value
    _save_profile(household_id, HouseholdProfile(**data))
    return f"Set profile.{field} to {data[field]}.", {}


def _exec_profile_note(household_id: str, p: dict) -> ExecResult:
    from api.profile import load_profile, _save_profile, HouseholdProfile
    note = str(p["note"]).strip()
    if not note:
        return "Empty note discarded.", {}
    current = load_profile(household_id)
    data = current.model_dump(exclude={"updated_at"})
    notes = list(data.get("notes", []))
    notes.append(note)
    data["notes"] = notes
    _save_profile(household_id, HouseholdProfile(**data))
    return f"Recorded note: {note}", {}


# Async executors need special handling; keep the mapping separate.
_EXECUTORS: dict[str, callable] = {
    "recipe.rename": _exec_recipe_rename,
    "recipe.servings": _exec_recipe_servings,
    "recipe.delete": _exec_recipe_delete,
    "recipe.create": _exec_recipe_create,  # async
    "plan.create": _exec_plan_create,
    "plan.delete": _exec_plan_delete,
    "plan.add_entry": _exec_plan_add_entry,
    "plan.remove_entry": _exec_plan_remove_entry,
    "plan.update_portions": _exec_plan_update_portions,
    "profile.field": _exec_profile_field,
    "profile.note": _exec_profile_note,
}

_ASYNC_KINDS = {"recipe.create"}


async def execute(kind: str, household_id: str, params: dict) -> ExecResult:
    fn = _EXECUTORS.get(kind)
    if not fn:
        return f"Unknown action kind '{kind}'.", {}
    if kind in _ASYNC_KINDS:
        return await fn(household_id, params)
    return fn(household_id, params)


# ============================================================
# Endpoints
# ============================================================


def _load_pending(pid: str) -> dict | None:
    with get_recipe_db() as conn:
        row = conn.execute(
            "SELECT id, session_id, household_id, kind, summary, params, status, "
            "result, created_at, resolved_at FROM pending_actions WHERE id = ?",
            [pid],
        ).fetchone()
    return dict(row) if row else None


@router.post("/{pid}/accept", response_model=ResolveResponse)
async def accept_pending(pid: str):
    p = _load_pending(pid)
    if not p:
        raise HTTPException(404, "Pending action not found")
    if p["status"] != "pending":
        raise HTTPException(409, f"Already {p['status']}")

    try:
        params = json.loads(p["params"] or "{}")
    except json.JSONDecodeError:
        params = {}

    created: dict[str, str] = {}
    try:
        result, created = await execute(p["kind"], p["household_id"], params)
        status = "accepted"
    except Exception as e:
        result = f"Execution failed: {e}"
        status = "failed"

    with get_recipe_db() as conn:
        conn.execute(
            "UPDATE pending_actions SET status = ?, result = ?, "
            "resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
            [status, result, pid],
        )
    return ResolveResponse(id=pid, status=status, result=result, created=created or None)


@router.post("/{pid}/reject", response_model=ResolveResponse)
def reject_pending(pid: str):
    p = _load_pending(pid)
    if not p:
        raise HTTPException(404, "Pending action not found")
    if p["status"] != "pending":
        raise HTTPException(409, f"Already {p['status']}")
    with get_recipe_db() as conn:
        conn.execute(
            "UPDATE pending_actions SET status = 'rejected', "
            "resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
            [pid],
        )
    return ResolveResponse(id=pid, status="rejected", result=None, created=None)


@router.get("/sessions/{sid}", response_model=list[PendingActionOut])
def list_pending_for_session(sid: str, only_pending: bool = False):
    """List proposals for a session. Used on chat reload so pending items persist
    across page refreshes."""
    q = (
        "SELECT id, kind, summary, params, status, result, created_at, resolved_at "
        "FROM pending_actions WHERE session_id = ?"
    )
    args: list = [sid]
    if only_pending:
        q += " AND status = 'pending'"
    q += " ORDER BY created_at ASC"
    with get_recipe_db() as conn:
        rows = conn.execute(q, args).fetchall()
    out = []
    for r in rows:
        try:
            params = json.loads(r["params"] or "{}")
        except json.JSONDecodeError:
            params = {}
        out.append(PendingActionOut(
            id=r["id"], kind=r["kind"], summary=r["summary"], params=params,
            status=r["status"], result=r["result"],
            created_at=r["created_at"], resolved_at=r["resolved_at"],
        ))
    return out
