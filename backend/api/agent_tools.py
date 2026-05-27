"""Tool functions exposed to the chat agent (Postgres-backed).

Read tools run inline. Write tools do NOT mutate directly — they call
`PendingProposer.propose(...)` so the user can Accept or Reject each action
from the UI.

All reads use `user_tx(user)` so RLS auto-scopes to the user's household.
"""

from __future__ import annotations

from api.auth import CurrentUser
from api.db import user_tx
from api.ingredients import load_all_curated_meta
from api.pending_actions import PendingProposer
from api.profile import coerce_profile_value


def register_all(
    agent,
    household_id: str,
    proposer: PendingProposer,
    user: CurrentUser,
) -> None:
    """Register all tools on a PydanticAI agent."""

    # =========================================================
    # READ — run inline
    # =========================================================

    @agent.tool_plain
    async def list_recipes() -> str:
        """List all saved recipes in the household. Returns id, name, servings."""
        async with user_tx(user) as conn:
            rows = await conn.fetch(
                "SELECT id::text AS id, name, servings FROM hearth.recipes "
                "ORDER BY updated_at DESC"
            )
        if not rows:
            return "No recipes saved yet."
        return "\n".join(
            f"id={r['id']} | {r['name']} (serves {r['servings']})" for r in rows
        )

    @agent.tool_plain
    async def search_recipes(query: str) -> str:
        """Search saved recipes by name (case-insensitive substring)."""
        async with user_tx(user) as conn:
            rows = await conn.fetch(
                "SELECT id::text AS id, name, servings FROM hearth.recipes "
                "WHERE lower(name) LIKE $1 ORDER BY updated_at DESC",
                f"%{query.lower()}%",
            )
        if not rows:
            return f"No saved recipes match '{query}'."
        return "\n".join(
            f"id={r['id']} | {r['name']} (serves {r['servings']})" for r in rows
        )

    @agent.tool_plain
    async def get_recipe(recipe_id: str) -> str:
        """Get full details of a saved recipe: name, servings, ingredients, instructions."""
        async with user_tx(user) as conn:
            row = await conn.fetchrow(
                "SELECT id::text AS id, name, servings, instructions "
                "FROM hearth.recipes WHERE id = $1::uuid",
                recipe_id,
            )
            if row is None:
                return f"Recipe {recipe_id} not found."
            ing_rows = await conn.fetch(
                "SELECT fdc_id, quantity_g FROM hearth.recipe_ingredients "
                "WHERE recipe_id = $1::uuid",
                recipe_id,
            )

        meta = load_all_curated_meta()
        instructions = row["instructions"] if isinstance(row["instructions"], list) else []

        ing_lines = []
        for ing in ing_rows:
            name = meta.get(ing["fdc_id"], {}).get(
                "simple_name", f"unknown ({ing['fdc_id']})"
            )
            ing_lines.append(
                f"  - {name}: {float(ing['quantity_g'])}g (fdc_id={ing['fdc_id']})"
            )

        instr_lines = [f"  {i+1}. {s}" for i, s in enumerate(instructions)]

        return (
            f"id={row['id']} | {row['name']} (serves {row['servings']})\n"
            f"Ingredients:\n" + ("\n".join(ing_lines) or "  (none)") + "\n"
            f"Instructions:\n" + ("\n".join(instr_lines) or "  (none)")
        )

    @agent.tool_plain
    async def list_meal_plans() -> str:
        """List all meal plans for the household."""
        async with user_tx(user) as conn:
            rows = await conn.fetch(
                "SELECT id::text AS id, name, start_date FROM hearth.meal_plans "
                "ORDER BY start_date DESC"
            )
        if not rows:
            return "No meal plans yet."
        return "\n".join(
            f"id={r['id']} | {r['name']} "
            f"(starts {r['start_date'].isoformat() if r['start_date'] else ''})"
            for r in rows
        )

    @agent.tool_plain
    async def get_meal_plan(plan_id: str) -> str:
        """Get full details of a meal plan: all entries with date, slot, recipe, portions."""
        async with user_tx(user) as conn:
            plan = await conn.fetchrow(
                "SELECT id::text AS id, name, start_date FROM hearth.meal_plans "
                "WHERE id = $1::uuid",
                plan_id,
            )
            if plan is None:
                return f"Meal plan {plan_id} not found."
            entries = await conn.fetch(
                """
                SELECT e.id::text AS id, e.recipe_id::text AS recipe_id,
                       e.plan_date, e.slot, e.portions, r.name AS recipe_name
                FROM hearth.meal_plan_entries e
                LEFT JOIN hearth.recipes r ON r.id = e.recipe_id
                WHERE e.meal_plan_id = $1::uuid
                ORDER BY e.plan_date, e.slot
                """,
                plan_id,
            )

        lines = [
            f"Plan id={plan['id']} | {plan['name']} "
            f"(starts {plan['start_date'].isoformat() if plan['start_date'] else ''})"
        ]
        if not entries:
            lines.append("  (no entries yet)")
        for e in entries:
            slot = e["slot"] or "-"
            lines.append(
                f"  entry_id={e['id']} | "
                f"{e['plan_date'].isoformat() if e['plan_date'] else ''} {slot}: "
                f"{e['recipe_name'] or '???'} "
                f"(recipe_id={e['recipe_id']}, portions={float(e['portions'])})"
            )
        return "\n".join(lines)

    @agent.tool_plain
    def search_pantry(query: str) -> str:
        """Search the curated pantry (cache-backed) for ingredients."""
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
    async def search_usda(query: str, limit: int = 25) -> str:
        """Search the full USDA database (~8k items) by name."""
        like = f"%{query.lower()}%"
        async with user_tx(user) as conn:
            rows = await conn.fetch(
                """
                SELECT fdc_id, description, food_group FROM hearth.usda_ingredients
                WHERE lower(description) LIKE $1
                ORDER BY length(description), description LIMIT $2
                """,
                like, limit,
            )
        if not rows:
            return f"No USDA ingredient matches '{query}'."
        return "\n".join(
            f"fdc_id={r['fdc_id']} | {r['description']} (group: {r['food_group']})"
            for r in rows
        )

    @agent.tool_plain
    async def get_profile() -> str:
        """Read the household profile — dietary needs, likes/dislikes, etc."""
        from api.profile import load_profile, render_profile_context
        return render_profile_context(await load_profile(household_id))

    @agent.tool_plain
    async def household_summary() -> str:
        """State-of-the-app summary: counts of recipes, meal plans, pantry items."""
        async with user_tx(user) as conn:
            n_recipes = await conn.fetchval(
                "SELECT COUNT(*) FROM hearth.recipes"
            )
            n_plans = await conn.fetchval(
                "SELECT COUNT(*) FROM hearth.meal_plans"
            )
        n_curated = len(load_all_curated_meta())
        return (
            f"Household summary:\n"
            f"  saved recipes: {n_recipes}\n"
            f"  meal plans: {n_plans}\n"
            f"  pantry: {n_curated} ingredients (curated catalog)"
        )

    # =========================================================
    # WRITE — propose for user approval
    # =========================================================

    def _preview(kind: str, summary: str, params: dict) -> str:
        pid = proposer.propose(kind, summary, params)
        return f"Proposed (id={pid}): {summary}. Waiting for the user to accept."

    @agent.tool_plain
    async def propose_rename_recipe(recipe_id: str, new_name: str) -> str:
        """PROPOSE renaming a saved recipe. Does NOT apply the change — the user
        must accept it in the UI."""
        async with user_tx(user) as conn:
            row = await conn.fetchrow(
                "SELECT name FROM hearth.recipes WHERE id = $1::uuid",
                recipe_id,
            )
        if row is None:
            return f"Recipe {recipe_id} not found."
        return _preview(
            "recipe.rename",
            f"Rename '{row['name']}' -> '{new_name}'",
            {"recipe_id": recipe_id, "new_name": new_name},
        )

    @agent.tool_plain
    async def propose_update_recipe_servings(recipe_id: str, servings: int) -> str:
        """PROPOSE changing a recipe's base serving count."""
        async with user_tx(user) as conn:
            row = await conn.fetchrow(
                "SELECT name FROM hearth.recipes WHERE id = $1::uuid",
                recipe_id,
            )
        if row is None:
            return f"Recipe {recipe_id} not found."
        return _preview(
            "recipe.servings",
            f"Set '{row['name']}' to {servings} servings",
            {"recipe_id": recipe_id, "servings": int(servings)},
        )

    @agent.tool_plain
    async def propose_delete_recipe(recipe_id: str) -> str:
        """PROPOSE deleting a recipe."""
        async with user_tx(user) as conn:
            row = await conn.fetchrow(
                "SELECT name FROM hearth.recipes WHERE id = $1::uuid",
                recipe_id,
            )
        if row is None:
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
    async def propose_delete_meal_plan(plan_id: str) -> str:
        """PROPOSE deleting a meal plan."""
        async with user_tx(user) as conn:
            row = await conn.fetchrow(
                "SELECT name FROM hearth.meal_plans WHERE id = $1::uuid",
                plan_id,
            )
        if row is None:
            return f"Meal plan {plan_id} not found."
        return _preview(
            "plan.delete",
            f"Delete meal plan '{row['name']}'",
            {"plan_id": plan_id},
        )

    @agent.tool_plain
    async def propose_add_meal_to_plan(
        plan_id: str, recipe_id: str, plan_date: str,
        slot: str = "dinner", portions: float = 1,
    ) -> str:
        """PROPOSE adding a recipe to a meal plan on a specific date and slot."""
        async with user_tx(user) as conn:
            plan = await conn.fetchrow(
                "SELECT name FROM hearth.meal_plans WHERE id = $1::uuid",
                plan_id,
            )
            if plan is None:
                return f"Meal plan {plan_id} not found."
            recipe = await conn.fetchrow(
                "SELECT name FROM hearth.recipes WHERE id = $1::uuid",
                recipe_id,
            )
            if recipe is None:
                return f"Recipe {recipe_id} not found."
        return _preview(
            "plan.add_entry",
            f"Add '{recipe['name']}' to '{plan['name']}' on "
            f"{plan_date} {slot} ({portions} portions)",
            {
                "plan_id": plan_id, "recipe_id": recipe_id, "plan_date": plan_date,
                "slot": slot, "portions": float(portions),
            },
        )

    @agent.tool_plain
    async def propose_remove_meal_from_plan(entry_id: str) -> str:
        """PROPOSE removing a single entry from a meal plan."""
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
            return f"Entry {entry_id} not found."
        return _preview(
            "plan.remove_entry",
            f"Remove '{row['recipe_name']}' from "
            f"{row['plan_date'].isoformat() if row['plan_date'] else ''} {row['slot']}",
            {"entry_id": entry_id},
        )

    @agent.tool_plain
    async def propose_update_entry_portions(entry_id: str, portions: float) -> str:
        """PROPOSE changing the portions on a meal plan entry."""
        async with user_tx(user) as conn:
            row = await conn.fetchrow(
                """
                SELECT r.name AS recipe_name FROM hearth.meal_plan_entries e
                LEFT JOIN hearth.recipes r ON r.id = e.recipe_id
                WHERE e.id = $1::uuid
                """,
                entry_id,
            )
        if row is None:
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
        (int minutes), batch_cook_preference ('none'|'moderate'|'heavy'),
        budget_level ('thrifty'|'moderate'|'splurge')."""
        try:
            coerced = coerce_profile_value(field, value)
        except ValueError as e:
            return str(e)
        return _preview(
            "profile.field",
            f"Set profile.{field} to {coerced!r}",
            {"field": field, "value": coerced},
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
