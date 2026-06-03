"""Pure, transport-agnostic tool implementations for the Hearth agent.

Each function takes a `ToolContext` and returns either a plain string (read
results / human-readable error) or, for writes, a `Proposal` descriptor. They
NEVER mutate the database — a write is realized only when the host applies an
accepted Proposal (see `api.pending_actions`). All reads use `user_tx(ctx.user)`
so Postgres RLS auto-scopes to the household.

These docstrings are the canonical tool descriptions: the MCP server exposes
them directly, and the in-process adapter mirrors them. Keep both in sync.
"""

from __future__ import annotations

import uuid
from datetime import date

from api.agent_core.context import Proposal, ToolContext
from api.db import user_tx
from api.ingredients import load_all_curated_meta
from api.profile import coerce_profile_value


def _is_uuid(value) -> bool:
    """True if `value` is a well-formed UUID string. Tools validate ids before
    querying so a mangled id from the LLM (e.g. an extra digit) returns a
    retryable error instead of crashing asyncpg's ::uuid cast."""
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False

# Both list_recipes and search_recipes rank by signals the agent should prefer
# when picking a meal: how many times the household has previously planned this
# recipe, and whether it came from an Explore like-swipe (public_origin_id IS
# NOT NULL). The system prompt tells the agent to favour the top results.
_RANKED_RECIPE_SELECT = """
    SELECT r.id::text AS id, r.name, r.servings, r.meal_type,
           COALESCE(p.times_planned, 0) AS times_planned,
           (r.public_origin_id IS NOT NULL) AS from_explore
    FROM hearth.recipes r
    LEFT JOIN (
        SELECT recipe_id, COUNT(*)::int AS times_planned
        FROM hearth.meal_plan_entries
        GROUP BY recipe_id
    ) p ON p.recipe_id = r.id
"""


def _format_recipe_row(r) -> str:
    tags = []
    if r["times_planned"]:
        tags.append(f"cooked {r['times_planned']}x")
    if r["from_explore"]:
        tags.append("from Explore")
    if r["meal_type"]:
        tags.append(r["meal_type"])
    tag_str = f" [{', '.join(tags)}]" if tags else ""
    return f"id={r['id']} | {r['name']} (serves {r['servings']}){tag_str}"


# =========================================================
# READ — run inline
# =========================================================


async def list_recipes(ctx: ToolContext) -> str:
    """List saved recipes in this household, ranked by familiarity:
    previously-cooked first, then Explore-liked, then everything else."""
    async with user_tx(ctx.user) as conn:
        rows = await conn.fetch(
            _RANKED_RECIPE_SELECT
            + " ORDER BY times_planned DESC, from_explore DESC, r.updated_at DESC"
        )
    if not rows:
        return "No recipes saved yet."
    return "\n".join(_format_recipe_row(r) for r in rows)


async def search_recipes(ctx: ToolContext, query: str) -> str:
    """Search saved recipes by name. Results are ranked so the
    household's already-cooked + Explore-liked recipes come first."""
    async with user_tx(ctx.user) as conn:
        rows = await conn.fetch(
            _RANKED_RECIPE_SELECT
            + " WHERE lower(r.name) LIKE $1 "
            + "ORDER BY times_planned DESC, from_explore DESC, r.updated_at DESC",
            f"%{query.lower()}%",
        )
    if not rows:
        return f"No saved recipes match '{query}'."
    return "\n".join(_format_recipe_row(r) for r in rows)


async def search_pool_recipes(ctx: ToolContext, query: str) -> str:
    """Search the global recipe pool (hearth.public_recipes) — starter
    library + community LLM-shared recipes. Use this when no saved recipe
    fits; the agent can then call propose_import_pool_recipe to bring
    one into the household without spending an LLM credit on a fresh gen."""
    async with user_tx(ctx.user) as conn:
        rows = await conn.fetch(
            """
            SELECT pr.id::text AS id, pr.name, pr.meal_type, pr.cuisine,
                   pr.dietary, pr.time_min, pr.source
            FROM hearth.public_recipes pr
            WHERE lower(pr.name) LIKE $1
            ORDER BY pr.source, pr.name
            LIMIT 25
            """,
            f"%{query.lower()}%",
        )
    if not rows:
        return f"No pool recipes match '{query}'. Consider proposing a fresh recipe generation."
    out = ["public_recipe_id | name [tags]"]
    for r in rows:
        tags = []
        if r["meal_type"]:
            tags.append(r["meal_type"])
        if r["cuisine"]:
            tags.append("/".join(r["cuisine"]))
        if r["dietary"]:
            tags.append("/".join(r["dietary"]))
        if r["time_min"]:
            tags.append(f"{r['time_min']}min")
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        out.append(f"{r['id']} | {r['name']}{tag_str}")
    return "\n".join(out)


async def get_recipe(ctx: ToolContext, recipe_id: str) -> str:
    """Get full details of a saved recipe: name, servings, ingredients, instructions."""
    if not _is_uuid(recipe_id):
        return f"Invalid recipe id '{recipe_id}'. Use an exact id from a search result."
    async with user_tx(ctx.user) as conn:
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
        "Ingredients:\n" + ("\n".join(ing_lines) or "  (none)") + "\n"
        "Instructions:\n" + ("\n".join(instr_lines) or "  (none)")
    )


async def search_pantry(ctx: ToolContext, query: str) -> str:
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


async def search_usda(ctx: ToolContext, query: str, limit: int = 25) -> str:
    """Search the full USDA database (~8k items) by name."""
    like = f"%{query.lower()}%"
    async with user_tx(ctx.user) as conn:
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


async def get_profile(ctx: ToolContext) -> str:
    """Read the household profile — dietary needs, likes/dislikes, etc."""
    from api.profile import load_profile, render_profile_context
    return render_profile_context(await load_profile(ctx.household_id))


async def household_summary(ctx: ToolContext) -> str:
    """State-of-the-app summary: counts of recipes, meal plans, pantry items."""
    async with user_tx(ctx.user) as conn:
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


async def list_calendar_meals(ctx: ToolContext, start_date: str, end_date: str) -> str:
    """List meals already on the household calendar between two dates
    (inclusive, ISO YYYY-MM-DD). Use this to check what's already planned
    before proposing additions, and to find entry_ids when the user wants
    to remove or change something."""
    try:
        sd, ed = date.fromisoformat(start_date), date.fromisoformat(end_date)
    except ValueError:
        return (
            f"Invalid date — use ISO YYYY-MM-DD "
            f"(got start={start_date!r}, end={end_date!r})."
        )
    async with user_tx(ctx.user) as conn:
        rows = await conn.fetch(
            """
            SELECT e.id::text AS entry_id, e.plan_date, e.slot, e.portions,
                   r.name AS recipe_name
            FROM hearth.meal_plan_entries e
            LEFT JOIN hearth.recipes r ON r.id = e.recipe_id
            WHERE e.plan_date BETWEEN $1::date AND $2::date
            ORDER BY e.plan_date, e.slot
            """,
            sd, ed,
        )
    if not rows:
        return f"Nothing planned between {start_date} and {end_date}."
    return "\n".join(
        f"entry_id={r['entry_id']} | {r['plan_date'].isoformat()} {r['slot']}: "
        f"{r['recipe_name']} ({r['portions']} portions)"
        for r in rows
    )


async def get_calendar_conflicts(
    ctx: ToolContext, start_date: str, end_date: str, slots: list[str],
) -> list[dict]:
    """Return existing calendar entries that occupy the given slots between two
    dates (inclusive, ISO YYYY-MM-DD). Structured (not a chat tool) — used by
    the week wizard's pre-flight to ask the user keep-or-replace per day before
    generating, so a freshly-generated plan never double-books an occupied day."""
    sd, ed = date.fromisoformat(start_date), date.fromisoformat(end_date)
    async with user_tx(ctx.user) as conn:
        rows = await conn.fetch(
            """
            SELECT e.id::text AS entry_id, e.plan_date, e.slot, e.portions,
                   e.recipe_id::text AS recipe_id, r.name AS recipe_name
            FROM hearth.meal_plan_entries e
            LEFT JOIN hearth.recipes r ON r.id = e.recipe_id
            WHERE e.plan_date BETWEEN $1::date AND $2::date
              AND e.slot = ANY($3::text[])
            ORDER BY e.plan_date, e.slot
            """,
            sd, ed, slots,
        )
    return [
        {
            "entry_id": r["entry_id"],
            "plan_date": r["plan_date"].isoformat() if r["plan_date"] else "",
            "slot": r["slot"],
            "recipe_id": r["recipe_id"],
            "recipe_name": r["recipe_name"],
            "portions": float(r["portions"]),
        }
        for r in rows
    ]


async def search_usda_for_staple(ctx: ToolContext, query: str) -> str:
    """Search the USDA ingredient catalogue for a name to use with
    propose_pantry_add or propose_pantry_remove. Returns fdc_id + name
    rows; pick the best fit for what the user described."""
    async with user_tx(ctx.user) as conn:
        rows = await conn.fetch(
            """
            SELECT fdc_id, description FROM hearth.usda_ingredients
            WHERE lower(description) LIKE $1
            ORDER BY length(description) ASC
            LIMIT 15
            """,
            f"%{query.lower()}%",
        )
    if not rows:
        return f"No USDA ingredient matches '{query}'."
    return "\n".join(f"fdc_id={r['fdc_id']} | {r['description']}" for r in rows)


# =========================================================
# WRITE — return a Proposal (host applies on accept)
# =========================================================


async def propose_rename_recipe(ctx: ToolContext, recipe_id: str, new_name: str) -> Proposal | str:
    """PROPOSE renaming a saved recipe. Does NOT apply the change — the user
    must accept it in the UI."""
    if not _is_uuid(recipe_id):
        return f"Invalid recipe id '{recipe_id}'."
    async with user_tx(ctx.user) as conn:
        row = await conn.fetchrow(
            "SELECT name FROM hearth.recipes WHERE id = $1::uuid",
            recipe_id,
        )
    if row is None:
        return f"Recipe {recipe_id} not found."
    return Proposal(
        kind="recipe.rename",
        summary=f"Rename '{row['name']}' -> '{new_name}'",
        params={"recipe_id": recipe_id, "new_name": new_name},
    )


async def propose_update_recipe_servings(ctx: ToolContext, recipe_id: str, servings: int) -> Proposal | str:
    """PROPOSE changing a recipe's base serving count."""
    if not _is_uuid(recipe_id):
        return f"Invalid recipe id '{recipe_id}'."
    async with user_tx(ctx.user) as conn:
        row = await conn.fetchrow(
            "SELECT name FROM hearth.recipes WHERE id = $1::uuid",
            recipe_id,
        )
    if row is None:
        return f"Recipe {recipe_id} not found."
    return Proposal(
        kind="recipe.servings",
        summary=f"Set '{row['name']}' to {servings} servings",
        params={"recipe_id": recipe_id, "servings": int(servings)},
    )


async def propose_delete_recipe(ctx: ToolContext, recipe_id: str) -> Proposal | str:
    """PROPOSE deleting a recipe."""
    if not _is_uuid(recipe_id):
        return f"Invalid recipe id '{recipe_id}'."
    async with user_tx(ctx.user) as conn:
        row = await conn.fetchrow(
            "SELECT name FROM hearth.recipes WHERE id = $1::uuid",
            recipe_id,
        )
    if row is None:
        return f"Recipe {recipe_id} not found."
    return Proposal(
        kind="recipe.delete",
        summary=f"Delete recipe '{row['name']}'",
        params={"recipe_id": recipe_id},
    )


async def propose_generate_recipe(ctx: ToolContext, prompt: str, servings: int = 4) -> Proposal | str:
    """PROPOSE generating a fresh recipe from scratch.

    Last resort — prefer propose_import_pool_recipe when search_pool_recipes
    already turned up something appropriate. Generation costs an LLM credit
    and takes ~30s; importing a pool recipe is instant and free."""
    return Proposal(
        kind="recipe.create",
        summary=f"Generate and save recipe: '{prompt}' (base servings {servings})",
        params={"prompt": prompt, "servings": int(servings)},
    )


async def propose_import_pool_recipe(ctx: ToolContext, public_recipe_id: str) -> Proposal | str:
    """PROPOSE importing an existing recipe from the global pool into this
    household's saved recipes. Free, instant — no LLM credit spent.
    Use this whenever search_pool_recipes returns a fit."""
    if not _is_uuid(public_recipe_id):
        return f"Invalid pool recipe id '{public_recipe_id}'."
    async with user_tx(ctx.user) as conn:
        row = await conn.fetchrow(
            "SELECT name FROM hearth.public_recipes WHERE id = $1::uuid",
            public_recipe_id,
        )
    if row is None:
        return f"Pool recipe {public_recipe_id} not found."
    return Proposal(
        kind="recipe.import_from_pool",
        summary=f"Import '{row['name']}' from the recipe library",
        params={"public_recipe_id": public_recipe_id},
    )


async def propose_add_meal_to_calendar(
    ctx: ToolContext, recipe_id: str, plan_date: str,
    slot: str = "dinner", portions: float = 1,
) -> Proposal | str:
    """PROPOSE putting a recipe on the household calendar for a specific
    date and slot. Use this — not the old plan-based variant — for any
    meal-adding interaction. plan_date is ISO YYYY-MM-DD; slot is
    breakfast/lunch/dinner."""
    if not _is_uuid(recipe_id):
        return f"Invalid recipe id '{recipe_id}'."
    async with user_tx(ctx.user) as conn:
        recipe = await conn.fetchrow(
            "SELECT name FROM hearth.recipes WHERE id = $1::uuid",
            recipe_id,
        )
        if recipe is None:
            return f"Recipe {recipe_id} not found."
    return Proposal(
        kind="calendar.add_meal",
        summary=f"Add '{recipe['name']}' to the calendar on "
                f"{plan_date} {slot} ({portions} portions)",
        params={
            "recipe_id": recipe_id, "plan_date": plan_date,
            "slot": slot, "portions": float(portions),
        },
    )


async def propose_remove_meal_from_calendar(ctx: ToolContext, entry_id: str) -> Proposal | str:
    """PROPOSE removing a single meal from the household calendar."""
    if not _is_uuid(entry_id):
        return f"Invalid meal id '{entry_id}'."
    async with user_tx(ctx.user) as conn:
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
        return f"Meal {entry_id} not found."
    return Proposal(
        kind="calendar.remove_meal",
        summary=f"Remove '{row['recipe_name']}' from "
                f"{row['plan_date'].isoformat() if row['plan_date'] else ''} {row['slot']}",
        params={"entry_id": entry_id},
    )


async def propose_update_meal_portions(ctx: ToolContext, entry_id: str, portions: float) -> Proposal | str:
    """PROPOSE changing the portions for a meal on the calendar."""
    if not _is_uuid(entry_id):
        return f"Invalid meal id '{entry_id}'."
    async with user_tx(ctx.user) as conn:
        row = await conn.fetchrow(
            """
            SELECT r.name AS recipe_name FROM hearth.meal_plan_entries e
            LEFT JOIN hearth.recipes r ON r.id = e.recipe_id
            WHERE e.id = $1::uuid
            """,
            entry_id,
        )
    if row is None:
        return f"Meal {entry_id} not found."
    return Proposal(
        kind="calendar.update_portions",
        summary=f"Set portions for '{row['recipe_name']}' to {portions}",
        params={"entry_id": entry_id, "portions": float(portions)},
    )


async def propose_pantry_add(ctx: ToolContext, fdc_id: int) -> Proposal | str:
    """PROPOSE adding an ingredient to the household pantry (the
    always-have-on-hand list). Use when the user says they have
    something in the kitchen — "I picked up a 1L bottle of olive oil"
    / "we bought saffron". The pantry shapes the shopping list and
    the recipe view: anything here is omitted from the buy list and
    shown under 'From your pantry'. Look up the fdc_id with
    search_usda_for_staple first."""
    async with user_tx(ctx.user) as conn:
        row = await conn.fetchrow(
            "SELECT description FROM hearth.usda_ingredients WHERE fdc_id = $1",
            fdc_id,
        )
    if row is None:
        return f"fdc_id={fdc_id} not in USDA catalogue."
    return Proposal(
        kind="pantry.add",
        summary=f"Add '{row['description']}' to the pantry",
        params={"fdc_id": int(fdc_id)},
    )


async def propose_pantry_remove(ctx: ToolContext, fdc_id: int) -> Proposal | str:
    """PROPOSE removing an ingredient from the household pantry. Use when
    the user says they've run out ("we're out of soy sauce", "finished
    the harissa"). After accept, the next shopping list will include it."""
    async with user_tx(ctx.user) as conn:
        row = await conn.fetchrow(
            "SELECT description FROM hearth.usda_ingredients WHERE fdc_id = $1",
            fdc_id,
        )
    if row is None:
        return f"fdc_id={fdc_id} not in USDA catalogue."
    return Proposal(
        kind="pantry.remove",
        summary=f"Remove '{row['description']}' from the pantry",
        params={"fdc_id": int(fdc_id)},
    )


async def propose_profile_field(ctx: ToolContext, field: str, value: str) -> Proposal | str:
    """PROPOSE updating a structured profile field. ALWAYS prefer this over
    propose_profile_note when the user's statement maps to a structured field.

    Supported fields:
      - family_size (int)
      - dietary / allergies / dislikes / likes / cuisines /
        kitchen_equipment (comma-separated list)
      - typical_cook_time_min (int minutes)
      - batch_cook_preference ('none' | 'moderate' | 'heavy')
      - budget_level ('thrifty' | 'moderate' | 'splurge')
      - visible_slots (comma-separated subset of breakfast,lunch,dinner —
        controls which slot rows render on the household calendar).
        Use this whenever the user says they don't plan a particular meal
        ("we skip breakfast", "lunch never gets used"). For "no breakfast"
        set visible_slots to "lunch,dinner". For "only dinner" set it to
        "dinner". Empty / unset means show all three.

    propose_profile_note is the LAST resort — only use it for genuinely
    free-form observations that no structured field captures."""
    try:
        coerced = coerce_profile_value(field, value)
    except ValueError as e:
        return str(e)
    return Proposal(
        kind="profile.field",
        summary=f"Set profile.{field} to {coerced!r}",
        params={"field": field, "value": coerced},
    )


async def propose_profile_note(ctx: ToolContext, note: str) -> Proposal | str:
    """PROPOSE appending an observation to the household profile notes."""
    note = note.strip()
    if not note:
        return "Empty note — nothing to propose."
    return Proposal(
        kind="profile.note",
        summary=f"Add note: {note}",
        params={"note": note},
    )
