"""Tool functions exposed to the chat agent.

Design: read tools run inline. Write tools do NOT mutate directly — they call
`PendingProposer.propose(...)` so the user can Accept or Reject each action
from the UI. This is the human-in-the-loop safety net: the agent can suggest
as freely as it wants; nothing changes until the user agrees.

Tools still return human-readable strings so the LLM has something to reason
over for subsequent turns (e.g. "I proposed creating recipe X; it's pending
your approval").
"""

from __future__ import annotations

import json

from api.database import get_connection
from api.ingredients import load_all_curated_meta
from api.pending_actions import PendingProposer
from api.profile import PROFILE_FIELDS
from api.recipe_db import get_recipe_db


def register_all(agent, household_id: str, proposer: PendingProposer) -> None:
    """Register all tools on a PydanticAI agent.

    Mutating tools route through `proposer.propose(...)` instead of writing.
    Read tools run inline."""

    # =========================================================
    # READ — run inline
    # =========================================================

    @agent.tool_plain
    def list_recipes() -> str:
        """List all saved recipes in the household. Returns id, name, servings."""
        with get_recipe_db() as conn:
            rows = conn.execute(
                "SELECT id, name, servings FROM recipes WHERE household_id = ? "
                "ORDER BY updated_at DESC",
                [household_id],
            ).fetchall()
        if not rows:
            return "No recipes saved yet."
        return "\n".join(
            f"id={r['id']} | {r['name']} (serves {r['servings']})" for r in rows
        )

    @agent.tool_plain
    def search_recipes(query: str) -> str:
        """Search saved recipes by name (case-insensitive substring)."""
        with get_recipe_db() as conn:
            rows = conn.execute(
                "SELECT id, name, servings FROM recipes "
                "WHERE household_id = ? AND lower(name) LIKE ? "
                "ORDER BY updated_at DESC",
                [household_id, f"%{query.lower()}%"],
            ).fetchall()
        if not rows:
            return f"No saved recipes match '{query}'."
        return "\n".join(
            f"id={r['id']} | {r['name']} (serves {r['servings']})" for r in rows
        )

    @agent.tool_plain
    def get_recipe(recipe_id: str) -> str:
        """Get full details of a saved recipe: name, servings, ingredients, instructions."""
        with get_recipe_db() as conn:
            row = conn.execute(
                "SELECT * FROM recipes WHERE id = ? AND household_id = ?",
                [recipe_id, household_id],
            ).fetchone()
            if not row:
                return f"Recipe {recipe_id} not found."
            ingredients = conn.execute(
                "SELECT fdc_id, quantity_g FROM recipe_ingredients WHERE recipe_id = ?",
                [recipe_id],
            ).fetchall()

        meta = load_all_curated_meta()
        try:
            instructions = json.loads(row["instructions"]) if row["instructions"] else []
        except (json.JSONDecodeError, TypeError):
            instructions = []

        ing_lines = []
        for ing in ingredients:
            name = meta.get(ing["fdc_id"], {}).get("simple_name", f"unknown ({ing['fdc_id']})")
            ing_lines.append(f"  - {name}: {ing['quantity_g']}g (fdc_id={ing['fdc_id']})")

        instr_lines = [f"  {i+1}. {s}" for i, s in enumerate(instructions)]

        return (
            f"id={row['id']} | {row['name']} (serves {row['servings']})\n"
            f"Ingredients:\n" + ("\n".join(ing_lines) or "  (none)") + "\n"
            f"Instructions:\n" + ("\n".join(instr_lines) or "  (none)")
        )

    @agent.tool_plain
    def list_meal_plans() -> str:
        """List all meal plans for the household."""
        with get_recipe_db() as conn:
            rows = conn.execute(
                "SELECT id, name, start_date FROM meal_plans WHERE household_id = ? "
                "ORDER BY start_date DESC",
                [household_id],
            ).fetchall()
        if not rows:
            return "No meal plans yet."
        return "\n".join(
            f"id={r['id']} | {r['name']} (starts {r['start_date']})" for r in rows
        )

    @agent.tool_plain
    def get_meal_plan(plan_id: str) -> str:
        """Get full details of a meal plan: all entries with date, slot, recipe, portions."""
        with get_recipe_db() as conn:
            plan = conn.execute(
                "SELECT * FROM meal_plans WHERE id = ? AND household_id = ?",
                [plan_id, household_id],
            ).fetchone()
            if not plan:
                return f"Meal plan {plan_id} not found."
            entries = conn.execute(
                "SELECT e.id, e.recipe_id, e.plan_date, e.slot, e.portions, r.name AS recipe_name "
                "FROM meal_plan_entries e LEFT JOIN recipes r ON r.id = e.recipe_id "
                "WHERE e.meal_plan_id = ? ORDER BY e.plan_date, e.slot",
                [plan_id],
            ).fetchall()

        lines = [f"Plan id={plan['id']} | {plan['name']} (starts {plan['start_date']})"]
        if not entries:
            lines.append("  (no entries yet)")
        for e in entries:
            slot = e["slot"] or "-"
            lines.append(
                f"  entry_id={e['id']} | {e['plan_date']} {slot}: {e['recipe_name'] or '???'} "
                f"(recipe_id={e['recipe_id']}, portions={e['portions']})"
            )
        return "\n".join(lines)

    @agent.tool_plain
    def search_pantry(query: str) -> str:
        """Search the curated pantry (dbt seed ∪ user pantry) for ingredients."""
        meta = load_all_curated_meta()
        ql = query.lower()
        hits = [
            (fid, info) for fid, info in meta.items()
            if ql in info["simple_name"].lower() or ql in info["category"].lower()
        ]
        if not hits:
            return f"No pantry ingredient matches '{query}'."
        hits.sort(key=lambda x: x[1]["simple_name"])
        return "\n".join(
            f"fdc_id={fid} | {info['simple_name']} ({info['category']})"
            for fid, info in hits[:50]
        )

    @agent.tool_plain
    def search_usda(query: str, limit: int = 25) -> str:
        """Search the full USDA database (~8k items) by name."""
        like = f"%{query.lower()}%"
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT fdc_id, name, food_group FROM usda.ingredients "
                "WHERE lower(name) LIKE ? ORDER BY length(name), name LIMIT ?",
                [like, limit],
            ).fetchall()
        if not rows:
            return f"No USDA ingredient matches '{query}'."
        return "\n".join(
            f"fdc_id={r[0]} | {r[1]} (group: {r[2]})" for r in rows
        )

    @agent.tool_plain
    def get_profile() -> str:
        """Read the household profile — dietary needs, likes/dislikes, etc."""
        from api.profile import load_profile, render_profile_context
        return render_profile_context(load_profile(household_id))

    @agent.tool_plain
    def household_summary() -> str:
        """State-of-the-app summary: counts of recipes, meal plans, pantry items."""
        with get_recipe_db() as conn:
            n_recipes = conn.execute(
                "SELECT COUNT(*) AS c FROM recipes WHERE household_id = ?",
                [household_id],
            ).fetchone()["c"]
            n_plans = conn.execute(
                "SELECT COUNT(*) AS c FROM meal_plans WHERE household_id = ?",
                [household_id],
            ).fetchone()["c"]
            n_pantry = conn.execute("SELECT COUNT(*) AS c FROM pantry_ingredients").fetchone()["c"]
        n_curated = len(load_all_curated_meta())
        return (
            f"Household summary:\n"
            f"  saved recipes: {n_recipes}\n"
            f"  meal plans: {n_plans}\n"
            f"  pantry: {n_curated} ingredients ({n_pantry} user-promoted, "
            f"{n_curated - n_pantry} from curated seed)"
        )

    # =========================================================
    # WRITE — propose for user approval
    # =========================================================

    def _preview(kind: str, summary: str, params: dict) -> str:
        pid = proposer.propose(kind, summary, params)
        return f"Proposed (id={pid}): {summary}. Waiting for the user to accept."

    @agent.tool_plain
    def propose_rename_recipe(recipe_id: str, new_name: str) -> str:
        """PROPOSE renaming a saved recipe. Does NOT apply the change — the user
        must accept it in the UI."""
        with get_recipe_db() as conn:
            row = conn.execute(
                "SELECT name FROM recipes WHERE id = ? AND household_id = ?",
                [recipe_id, household_id],
            ).fetchone()
        if not row:
            return f"Recipe {recipe_id} not found."
        return _preview(
            "recipe.rename",
            f"Rename '{row['name']}' -> '{new_name}'",
            {"recipe_id": recipe_id, "new_name": new_name},
        )

    @agent.tool_plain
    def propose_update_recipe_servings(recipe_id: str, servings: int) -> str:
        """PROPOSE changing a recipe's base serving count."""
        with get_recipe_db() as conn:
            row = conn.execute(
                "SELECT name FROM recipes WHERE id = ? AND household_id = ?",
                [recipe_id, household_id],
            ).fetchone()
        if not row:
            return f"Recipe {recipe_id} not found."
        return _preview(
            "recipe.servings",
            f"Set '{row['name']}' to {servings} servings",
            {"recipe_id": recipe_id, "servings": int(servings)},
        )

    @agent.tool_plain
    def propose_delete_recipe(recipe_id: str) -> str:
        """PROPOSE deleting a recipe."""
        with get_recipe_db() as conn:
            row = conn.execute(
                "SELECT name FROM recipes WHERE id = ? AND household_id = ?",
                [recipe_id, household_id],
            ).fetchone()
        if not row:
            return f"Recipe {recipe_id} not found."
        return _preview(
            "recipe.delete",
            f"Delete recipe '{row['name']}'",
            {"recipe_id": recipe_id},
        )

    @agent.tool_plain
    def propose_generate_recipe(prompt: str, servings: int = 4) -> str:
        """PROPOSE generating and saving a new recipe from a short prompt.

        The generation itself only happens on accept — avoids wasting tokens on
        recipes the user doesn't want."""
        return _preview(
            "recipe.create",
            f"Generate and save recipe: '{prompt}' (base servings {servings})",
            {"prompt": prompt, "servings": int(servings)},
        )

    @agent.tool_plain
    def propose_create_meal_plan(name: str, start_date: str) -> str:
        """PROPOSE creating an empty meal plan. start_date is ISO YYYY-MM-DD."""
        return _preview(
            "plan.create",
            f"Create meal plan '{name}' starting {start_date}",
            {"name": name, "start_date": start_date},
        )

    @agent.tool_plain
    def propose_delete_meal_plan(plan_id: str) -> str:
        """PROPOSE deleting a meal plan."""
        with get_recipe_db() as conn:
            row = conn.execute(
                "SELECT name FROM meal_plans WHERE id = ? AND household_id = ?",
                [plan_id, household_id],
            ).fetchone()
        if not row:
            return f"Meal plan {plan_id} not found."
        return _preview(
            "plan.delete",
            f"Delete meal plan '{row['name']}'",
            {"plan_id": plan_id},
        )

    @agent.tool_plain
    def propose_add_meal_to_plan(
        plan_id: str, recipe_id: str, plan_date: str,
        slot: str = "dinner", portions: float = 1,
    ) -> str:
        """PROPOSE adding a recipe to a meal plan on a specific date and slot."""
        with get_recipe_db() as conn:
            plan = conn.execute(
                "SELECT name FROM meal_plans WHERE id = ? AND household_id = ?",
                [plan_id, household_id],
            ).fetchone()
            if not plan:
                return f"Meal plan {plan_id} not found."
            recipe = conn.execute(
                "SELECT name FROM recipes WHERE id = ? AND household_id = ?",
                [recipe_id, household_id],
            ).fetchone()
            if not recipe:
                return f"Recipe {recipe_id} not found."
        return _preview(
            "plan.add_entry",
            f"Add '{recipe['name']}' to '{plan['name']}' on {plan_date} {slot} ({portions} portions)",
            {
                "plan_id": plan_id, "recipe_id": recipe_id, "plan_date": plan_date,
                "slot": slot, "portions": float(portions),
            },
        )

    @agent.tool_plain
    def propose_remove_meal_from_plan(entry_id: str) -> str:
        """PROPOSE removing a single entry from a meal plan."""
        with get_recipe_db() as conn:
            row = conn.execute(
                "SELECT e.plan_date, e.slot, r.name AS recipe_name "
                "FROM meal_plan_entries e LEFT JOIN recipes r ON r.id = e.recipe_id "
                "WHERE e.id = ?",
                [entry_id],
            ).fetchone()
        if not row:
            return f"Entry {entry_id} not found."
        return _preview(
            "plan.remove_entry",
            f"Remove '{row['recipe_name']}' from {row['plan_date']} {row['slot']}",
            {"entry_id": entry_id},
        )

    @agent.tool_plain
    def propose_update_entry_portions(entry_id: str, portions: float) -> str:
        """PROPOSE changing the portions on a meal plan entry."""
        with get_recipe_db() as conn:
            row = conn.execute(
                "SELECT r.name AS recipe_name FROM meal_plan_entries e "
                "LEFT JOIN recipes r ON r.id = e.recipe_id WHERE e.id = ?",
                [entry_id],
            ).fetchone()
        if not row:
            return f"Entry {entry_id} not found."
        return _preview(
            "plan.update_portions",
            f"Set portions for '{row['recipe_name']}' to {portions}",
            {"entry_id": entry_id, "portions": float(portions)},
        )

    @agent.tool_plain
    def propose_profile_field(field: str, value: str) -> str:
        """PROPOSE updating a structured profile field.

        Supported fields: family_size (int), dietary/allergies/dislikes/likes/
        cuisines/kitchen_equipment (comma-separated list), typical_cook_time_min
        (int), batch_cook_preference ('none'|'moderate'|'heavy'), budget_level
        ('thrifty'|'moderate'|'splurge')."""
        if field not in PROFILE_FIELDS:
            return f"Unknown field '{field}'. Valid: {', '.join(PROFILE_FIELDS)}"
        return _preview(
            "profile.field",
            f"Set profile.{field} to {value!r}",
            {"field": field, "value": value},
        )

    @agent.tool_plain
    def propose_profile_note(note: str) -> str:
        """PROPOSE appending an observation to the household profile notes."""
        note = note.strip()
        if not note:
            return "Empty note — nothing to propose."
        return _preview(
            "profile.note",
            f"Add note: {note}",
            {"note": note},
        )
