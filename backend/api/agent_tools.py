"""Tool functions exposed to the chat agent.

Each function performs a real DB operation and returns a compact human-readable
string describing the outcome. Tools should be defensive (gracefully handle
missing IDs, invalid dates, etc.) so the LLM can recover from mistakes.

Usage: register tools on a PydanticAI Agent via `register_all(agent, household_id)`.
The household_id is a closure capture so the LLM never has to pass it around.
"""

from __future__ import annotations

import json
from typing import Callable

from api.database import get_connection
from api.ingredients import load_all_curated_meta
from api.recipe_db import get_recipe_db, new_id


# ============================================================
# Audit log
# ============================================================
# Track mutations performed during a single chat turn so the API can return them
# to the client (so the UI can show "Updated 'Tuesday dinner' to ...").

class AuditLog:
    def __init__(self):
        self.events: list[dict] = []

    def record(self, kind: str, summary: str, meta: dict | None = None):
        self.events.append({"kind": kind, "summary": summary, "meta": meta or {}})


# ============================================================
# Tool registration
# ============================================================

def register_all(agent, household_id: str, audit: AuditLog) -> None:
    """Register all tools on a PydanticAI agent for the given household."""

    # ---- Recipes (read) ----

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

    # ---- Recipes (write) ----

    @agent.tool_plain
    def update_recipe_name(recipe_id: str, new_name: str) -> str:
        """Rename a saved recipe."""
        with get_recipe_db() as conn:
            row = conn.execute(
                "SELECT name FROM recipes WHERE id = ? AND household_id = ?",
                [recipe_id, household_id],
            ).fetchone()
            if not row:
                return f"Recipe {recipe_id} not found."
            old = row["name"]
            conn.execute(
                "UPDATE recipes SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                [new_name, recipe_id],
            )
        audit.record("recipe.rename", f"Renamed '{old}' → '{new_name}'", {"recipe_id": recipe_id})
        return f"Renamed recipe {recipe_id}: '{old}' → '{new_name}'."

    @agent.tool_plain
    def update_recipe_servings(recipe_id: str, servings: int) -> str:
        """Change a recipe's base serving count (rescales nothing — quantities stay as stored)."""
        with get_recipe_db() as conn:
            row = conn.execute(
                "SELECT name FROM recipes WHERE id = ? AND household_id = ?",
                [recipe_id, household_id],
            ).fetchone()
            if not row:
                return f"Recipe {recipe_id} not found."
            conn.execute(
                "UPDATE recipes SET servings = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                [max(1, servings), recipe_id],
            )
        audit.record("recipe.servings", f"Set '{row['name']}' to {servings} servings", {"recipe_id": recipe_id})
        return f"Updated '{row['name']}' to {servings} servings."

    @agent.tool_plain
    def delete_recipe(recipe_id: str) -> str:
        """Delete a saved recipe permanently."""
        with get_recipe_db() as conn:
            row = conn.execute(
                "SELECT name FROM recipes WHERE id = ? AND household_id = ?",
                [recipe_id, household_id],
            ).fetchone()
            if not row:
                return f"Recipe {recipe_id} not found."
            conn.execute("DELETE FROM recipes WHERE id = ?", [recipe_id])
        audit.record("recipe.delete", f"Deleted recipe '{row['name']}'", {"recipe_id": recipe_id})
        return f"Deleted recipe '{row['name']}'."

    @agent.tool_plain
    async def generate_and_save_recipe(prompt: str, servings: int = 4) -> str:
        """Generate a new recipe via LLM from a prompt and save it.

        Use when the user asks to create a recipe from scratch or when populating
        a meal plan with a dish that doesn't exist yet."""
        from api.recipe_gen import generate_recipe

        try:
            gen = await generate_recipe(prompt)
        except Exception as e:
            return f"Recipe generation failed: {e}"

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
        audit.record(
            "recipe.create", f"Generated and saved recipe '{gen.name}'",
            {"recipe_id": recipe_id, "name": gen.name},
        )
        return (
            f"Created recipe id={recipe_id} | '{gen.name}' "
            f"with {len(gen.ingredients)} ingredients and {len(gen.instructions)} steps."
        )

    # ---- Meal plans ----

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
            slot = e["slot"] or "—"
            lines.append(
                f"  entry_id={e['id']} | {e['plan_date']} {slot}: {e['recipe_name'] or '???'} "
                f"(recipe_id={e['recipe_id']}, portions={e['portions']})"
            )
        return "\n".join(lines)

    @agent.tool_plain
    def create_meal_plan(name: str, start_date: str) -> str:
        """Create an empty meal plan. start_date is an ISO date like 2026-04-14."""
        plan_id = new_id()
        with get_recipe_db() as conn:
            conn.execute(
                "INSERT INTO meal_plans (id, household_id, name, start_date) VALUES (?, ?, ?, ?)",
                [plan_id, household_id, name, start_date],
            )
        audit.record(
            "plan.create", f"Created meal plan '{name}' starting {start_date}",
            {"plan_id": plan_id, "name": name},
        )
        return f"Created meal plan id={plan_id} | '{name}' starting {start_date}."

    @agent.tool_plain
    def add_meal_to_plan(
        plan_id: str, recipe_id: str, plan_date: str,
        slot: str = "dinner", portions: float = 1,
    ) -> str:
        """Add a recipe to a meal plan on a specific date and slot.

        slot: 'breakfast', 'lunch', or 'dinner'. plan_date: ISO date."""
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
            entry_id = new_id()
            conn.execute(
                "INSERT INTO meal_plan_entries (id, meal_plan_id, recipe_id, plan_date, slot, portions) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [entry_id, plan_id, recipe_id, plan_date, slot, portions],
            )
            conn.execute(
                "UPDATE meal_plans SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                [plan_id],
            )
        audit.record(
            "plan.add_entry",
            f"Added '{recipe['name']}' to {plan_date} {slot} (×{portions})",
            {"plan_id": plan_id, "entry_id": entry_id},
        )
        return (
            f"Added '{recipe['name']}' to '{plan['name']}' on {plan_date} {slot} "
            f"(portions={portions}, entry_id={entry_id})."
        )

    @agent.tool_plain
    def remove_meal_from_plan(entry_id: str) -> str:
        """Remove a single entry from a meal plan."""
        with get_recipe_db() as conn:
            row = conn.execute(
                "SELECT e.plan_date, e.slot, r.name AS recipe_name, e.meal_plan_id "
                "FROM meal_plan_entries e LEFT JOIN recipes r ON r.id = e.recipe_id "
                "WHERE e.id = ?",
                [entry_id],
            ).fetchone()
            if not row:
                return f"Entry {entry_id} not found."
            conn.execute("DELETE FROM meal_plan_entries WHERE id = ?", [entry_id])
            conn.execute(
                "UPDATE meal_plans SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                [row["meal_plan_id"]],
            )
        audit.record(
            "plan.remove_entry",
            f"Removed '{row['recipe_name']}' from {row['plan_date']} {row['slot']}",
            {"entry_id": entry_id},
        )
        return f"Removed '{row['recipe_name']}' from {row['plan_date']} {row['slot']}."

    @agent.tool_plain
    def update_entry_portions(entry_id: str, portions: float) -> str:
        """Change the portions for one entry in a meal plan."""
        with get_recipe_db() as conn:
            row = conn.execute(
                "SELECT e.plan_date, e.slot, r.name AS recipe_name, e.meal_plan_id "
                "FROM meal_plan_entries e LEFT JOIN recipes r ON r.id = e.recipe_id "
                "WHERE e.id = ?",
                [entry_id],
            ).fetchone()
            if not row:
                return f"Entry {entry_id} not found."
            conn.execute(
                "UPDATE meal_plan_entries SET portions = ? WHERE id = ?",
                [max(1, float(portions)), entry_id],
            )
            conn.execute(
                "UPDATE meal_plans SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                [row["meal_plan_id"]],
            )
        audit.record(
            "plan.update_portions",
            f"Set '{row['recipe_name']}' on {row['plan_date']} to {portions} portions",
            {"entry_id": entry_id},
        )
        return f"Updated portions for '{row['recipe_name']}' to {portions}."

    @agent.tool_plain
    def delete_meal_plan(plan_id: str) -> str:
        """Delete a meal plan and all its entries."""
        with get_recipe_db() as conn:
            row = conn.execute(
                "SELECT name FROM meal_plans WHERE id = ? AND household_id = ?",
                [plan_id, household_id],
            ).fetchone()
            if not row:
                return f"Meal plan {plan_id} not found."
            conn.execute("DELETE FROM meal_plans WHERE id = ?", [plan_id])
        audit.record("plan.delete", f"Deleted meal plan '{row['name']}'", {"plan_id": plan_id})
        return f"Deleted meal plan '{row['name']}'."

    # ---- Pantry / ingredients ----

    @agent.tool_plain
    def search_pantry(query: str) -> str:
        """Search the curated pantry (dbt seed ∪ user pantry) for ingredients matching a name or category."""
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
        """Search the full USDA database (~8k items) by name. Returns fdc_ids you can promote to the pantry or use directly."""
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

    # ---- Helpful summaries ----

    @agent.tool_plain
    def household_summary() -> str:
        """Quick state-of-the-app summary: counts of recipes, meal plans, pantry items."""
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
