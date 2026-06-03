"""Meal plan CRUD + shopping list generation from a plan + AI weekly generator
(Postgres-backed, RLS-scoped per household)."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path

import json

import asyncpg
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pydantic_ai import Agent

from api.auth import CurrentUser, get_current_user
from api.db import get_current_household_id, service_tx, user_tx
from api.models import (
    MealPlanCreate,
    MealPlanEntryOut,
    MealPlanOut,
    MealPlanUpdate,
    ShoppingListOut,
    ShoppingRecipeSelection,
)

log = logging.getLogger("mealplan.generate")
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

router = APIRouter(prefix="/meal-plans", tags=["meal-plans"])

# Descriptors + proteins stripped when reducing a dish name to its "family", so
# the HEAD noun survives: "Grilled Salmon Burgers", "Gourmet Salmon Burgers" and
# "Savory Salmon Burgers" all collapse to "burger" — the household wants one
# burger night, not a week of burger variants.
_DESC_WORDS = {
    # connectors / adjectives
    "with", "and", "the", "a", "of", "in", "on", "homemade", "classic", "fresh",
    "spicy", "creamy", "grilled", "roasted", "baked", "fried", "easy", "quick",
    "zesty", "savory", "hearty", "simple", "style", "served", "topped", "loaded",
    "gourmet", "spiced", "seared", "crispy", "tender", "juicy", "rich", "light",
    # proteins (so the family is the dish, not the filling)
    "beef", "chicken", "pork", "fish", "salmon", "cod", "tuna", "shrimp", "prawn",
    "turkey", "lamb", "tofu", "veggie", "vegetable", "vegetarian", "vegan", "bean",
    "lentil", "egg", "ham", "bacon", "sausage", "lax", "kyckling", "fläsk",
}


def _dish_family(text: str) -> str:
    """Coarse dish key for variety dedup. Cut the name at 'with'/'med'/comma to
    drop garnishes, strip descriptors + proteins, and return the singularised
    HEAD noun — so 'Grilled Salmon Burgers with Dressing', 'Gourmet Salmon
    Burgers' and 'Savory Salmon Burgers' all become 'burger'. Best paired with
    the model's short `dish_name`; also works on a recipe name or prompt."""
    head_part = re.split(r"\bwith\b|\bmed\b|[,(/]", (text or "").lower())[0]
    cleaned = re.sub(r"[^a-z0-9åäö ]+", " ", head_part)
    words = [w for w in cleaned.split() if w and w not in _DESC_WORDS]
    if not words:
        return ""
    head = words[-1]
    return head[:-1] if len(head) > 3 and head.endswith("s") else head


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


async def _build_plan_out(conn: asyncpg.Connection, plan_id: str) -> MealPlanOut:
    row = await conn.fetchrow(
        "SELECT id, household_id, name, start_date, created_at, updated_at "
        "FROM hearth.meal_plans WHERE id = $1::uuid",
        plan_id,
    )
    if row is None:
        raise HTTPException(404, "Meal plan not found")

    entries = await conn.fetch(
        """
        SELECT e.id, e.recipe_id, e.plan_date, e.slot, e.portions, r.name AS recipe_name
        FROM hearth.meal_plan_entries e
        LEFT JOIN hearth.recipes r ON r.id = e.recipe_id
        WHERE e.meal_plan_id = $1::uuid
        ORDER BY e.plan_date, e.slot
        """,
        plan_id,
    )

    return MealPlanOut(
        id=str(row["id"]),
        household_id=str(row["household_id"]),
        name=row["name"],
        start_date=row["start_date"].isoformat() if row["start_date"] else "",
        entries=[
            MealPlanEntryOut(
                id=str(e["id"]),
                recipe_id=str(e["recipe_id"]),
                recipe_name=e["recipe_name"],
                plan_date=e["plan_date"].isoformat() if e["plan_date"] else "",
                slot=e["slot"],
                portions=float(e["portions"]),
            )
            for e in entries
        ],
        created_at=row["created_at"].isoformat() if row["created_at"] else "",
        updated_at=row["updated_at"].isoformat() if row["updated_at"] else "",
    )


async def _replace_entries(
    conn: asyncpg.Connection,
    plan_id: str,
    entries,
) -> None:
    # Resolve household_id from the parent plan (every entry needs it set
    # since the flat-calendar migration).
    household_id = await conn.fetchval(
        "SELECT household_id::text FROM hearth.meal_plans WHERE id = $1::uuid",
        plan_id,
    )
    await conn.execute(
        "DELETE FROM hearth.meal_plan_entries WHERE meal_plan_id = $1::uuid",
        plan_id,
    )
    for e in entries:
        await conn.execute(
            """
            INSERT INTO hearth.meal_plan_entries
                (household_id, meal_plan_id, recipe_id, plan_date, slot, portions)
            VALUES ($1::uuid, $2::uuid, $3::uuid, $4::date, $5, $6)
            """,
            household_id, plan_id, e.recipe_id, e.plan_date, e.slot, e.portions,
        )


async def _ensure_plan_visible(conn: asyncpg.Connection, plan_id: str) -> None:
    exists = await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM hearth.meal_plans WHERE id = $1::uuid)",
        plan_id,
    )
    if not exists:
        raise HTTPException(404, "Meal plan not found")


async def _list_existing_recipes_for_planner(
    conn: asyncpg.Connection,
) -> str:
    # RLS already scopes us to the user's household.
    rows = await conn.fetch(
        "SELECT id, name, servings FROM hearth.recipes "
        "ORDER BY updated_at DESC LIMIT 200"
    )
    if not rows:
        return "(no saved recipes — every meal must be generated fresh)"
    return "\n".join(
        f"id={r['id']} | {r['name']} (serves {r['servings']})" for r in rows
    )


# ----------------------------------------------------------------------------
# Plan CRUD
# ----------------------------------------------------------------------------


@router.get("", response_model=list[MealPlanOut])
async def list_meal_plans(user: CurrentUser = Depends(get_current_user)):
    async with user_tx(user) as conn:
        rows = await conn.fetch(
            "SELECT id::text AS id FROM hearth.meal_plans ORDER BY start_date DESC"
        )
        return [await _build_plan_out(conn, r["id"]) for r in rows]


@router.post("", response_model=MealPlanOut, status_code=201)
async def create_meal_plan(
    body: MealPlanCreate,
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    async with user_tx(user) as conn:
        new_row = await conn.fetchrow(
            """
            INSERT INTO hearth.meal_plans (household_id, name, start_date)
            VALUES ($1::uuid, $2, $3::date)
            RETURNING id::text AS id
            """,
            household_id, body.name, body.start_date,
        )
        plan_id = new_row["id"]
        await _replace_entries(conn, plan_id, body.entries)
        return await _build_plan_out(conn, plan_id)


class CalendarConflictOut(BaseModel):
    entry_id: str
    plan_date: str
    slot: str
    recipe_id: str | None = None
    recipe_name: str | None = None
    portions: float


@router.get("/conflicts", response_model=list[CalendarConflictOut])
async def calendar_conflicts(
    start: date,
    end: date,
    slots: list[str] = Query(default=["dinner"]),
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    """Existing meals occupying `slots` between `start` and `end` (inclusive).
    The week wizard calls this first to offer keep/replace per occupied day."""
    from api.agent_core.context import ToolContext
    from api.agent_core.tools import get_calendar_conflicts

    ctx = ToolContext(user=user, household_id=household_id)
    rows = await get_calendar_conflicts(ctx, start.isoformat(), end.isoformat(), slots)
    return [CalendarConflictOut(**r) for r in rows]


@router.get("/{plan_id}", response_model=MealPlanOut)
async def get_meal_plan(
    plan_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    async with user_tx(user) as conn:
        await _ensure_plan_visible(conn, plan_id)
        return await _build_plan_out(conn, plan_id)


@router.put("/{plan_id}", response_model=MealPlanOut)
async def update_meal_plan(
    plan_id: str,
    body: MealPlanUpdate,
    user: CurrentUser = Depends(get_current_user),
):
    async with user_tx(user) as conn:
        await _ensure_plan_visible(conn, plan_id)

        if body.name is not None:
            await conn.execute(
                "UPDATE hearth.meal_plans SET name = $1, updated_at = now() "
                "WHERE id = $2::uuid",
                body.name, plan_id,
            )
        if body.start_date is not None:
            await conn.execute(
                "UPDATE hearth.meal_plans SET start_date = $1::date, updated_at = now() "
                "WHERE id = $2::uuid",
                body.start_date, plan_id,
            )
        if body.entries is not None:
            await _replace_entries(conn, plan_id, body.entries)
            await conn.execute(
                "UPDATE hearth.meal_plans SET updated_at = now() WHERE id = $1::uuid",
                plan_id,
            )

        return await _build_plan_out(conn, plan_id)


@router.delete("/{plan_id}", status_code=204)
async def delete_meal_plan(
    plan_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    async with user_tx(user) as conn:
        await _ensure_plan_visible(conn, plan_id)
        await conn.execute(
            "DELETE FROM hearth.meal_plans WHERE id = $1::uuid",
            plan_id,
        )


# ============================================================
# AI weekly plan generator
# ============================================================


class SlotConfig(BaseModel):
    slot: str
    portions: float = 1
    distinct_meals: int | None = None


class GenerateMealPlanRequest(BaseModel):
    prompt: str
    start_date: date
    days: int = 7
    servings: int = 4
    slot_configs: list[SlotConfig] = [SlotConfig(slot="dinner")]
    # Calendar entry_ids the user chose to REPLACE in the pre-flight. Any other
    # already-occupied (date, slot) is KEPT: the planner skips it and the old
    # meal stays. Empty => keep every occupied day (never double-book).
    replace_entry_ids: list[str] = []


class _PlannedMeal(BaseModel):
    day_offset: int
    slot: str
    use_recipe_id: str | None = None
    new_recipe_prompt: str | None = None
    portions: float = 1
    # Short dish FAMILY in 1-2 words, lowercase, no adjectives/proteins — e.g.
    # "tacos", "burger", "curry", "stir fry", "pasta". The server enforces at
    # most one meal per family per plan (non-batch), so "beef tacos" and "fish
    # tacos" (both family "tacos") never fill the week together.
    dish_name: str | None = None
    # True if the dish reheats / travels well as a next-day lunchbox (stews,
    # curries, pasta bakes, grain bowls, roasts) — false for crispy/fresh/fried
    # things, burgers, leafy salads, delicate fish. The server reuses only
    # lunchbox-friendly dishes as leftovers when filling extra days.
    lunchbox_friendly: bool = False
    # When generating (new_recipe_prompt), a short note on WHY a fresh recipe
    # instead of reusing — e.g. "no saved/pool match" or "user asked to try it".
    # Surfaced to the user so generation is never silent.
    reason: str | None = None


class _PlannedWeek(BaseModel):
    plan_name: str
    meals: list[_PlannedMeal]


_PLAN_MODEL = os.getenv("OPENAI_RECIPE_MODEL", "openai:gpt-4o")


def _assemble_week(
    planned_meals: list[_PlannedMeal],
    *,
    saved_rows,
    kept: list[dict],
    kept_cells: set[tuple[int, str]],
    slot_by_name: dict[str, SlotConfig],
    days: int,
    lunchbox_mode: bool,
    brief: str,
) -> tuple[list[_PlannedMeal], list[str], dict[str, str]]:
    """Turn the planner's raw meals into the final, variety-enforced plan.

    The model ignores prompt-level variety rules, so the constraints are
    enforced here instead. Steps:
      1. Validate: in-range day, known slot, has a source, one meal per cell,
         a recipe/prompt isn't split across slots, and kept (already-planned)
         cells are never touched.
      2. Dish-family dedup (non-batch slots): different recipes that are really
         the SAME dish — "Grilled/Gourmet/Savory Salmon Burgers" all family
         "burger" — collapse to one day. Named dishes therefore land once.
      3. Backfill the freed days with "unique dishes OR lunchboxes": a DIFFERENT
         saved dish (reuse-first), or leftovers of a lunchbox-friendly dish
         already on the plan, or — last resort — a fresh distinct generation.
         Default leans unique; lunchbox/matlåda mode leans on leftovers.

    Returns (valid_meals, unique_prompts, prompt_to_reason).
    """
    saved_by_id = {r["id"]: r for r in saved_rows}

    def _meal_family(m: _PlannedMeal) -> str:
        if m.dish_name and m.dish_name.strip():
            return _dish_family(m.dish_name)
        if m.use_recipe_id:
            name = saved_by_id.get(m.use_recipe_id, {}).get("name", "")
            return _dish_family(name) or f"id:{m.use_recipe_id}"
        return _dish_family(m.new_recipe_prompt or "")

    # 1) Basic validation + one-meal-per-cell + slot-disjoint + skip kept cells.
    valid_meals: list[_PlannedMeal] = []
    prompt_to_slot: dict[str, str] = {}
    recipe_id_to_slot: dict[str, str] = {}
    filled_cells: set[tuple[int, str]] = set()
    for meal in planned_meals:
        if meal.day_offset < 0 or meal.day_offset >= days:
            continue
        if meal.slot not in slot_by_name:
            continue
        cell = (meal.day_offset, meal.slot)
        if cell in kept_cells or cell in filled_cells:
            continue
        if not meal.use_recipe_id and not meal.new_recipe_prompt:
            continue
        # Never both: prefer reusing an existing recipe over an orphan generation
        # (the model is told "never both" but sometimes sets both anyway).
        if meal.use_recipe_id and meal.new_recipe_prompt:
            meal.new_recipe_prompt = None
        if meal.use_recipe_id:
            prior = recipe_id_to_slot.get(meal.use_recipe_id)
            if prior and prior != meal.slot:
                continue
            recipe_id_to_slot[meal.use_recipe_id] = meal.slot
        if meal.new_recipe_prompt:
            prior = prompt_to_slot.get(meal.new_recipe_prompt)
            if prior and prior != meal.slot:
                continue
            prompt_to_slot[meal.new_recipe_prompt] = meal.slot
        filled_cells.add(cell)
        valid_meals.append(meal)

    # 2) Dish-family dedup: one recipe per family per slot (non-batch).
    used_fam: dict[str, set[str]] = {}   # slot -> dish families already taken
    used_ids: dict[str, set[str]] = {}   # slot -> recipe ids already taken
    for c in kept:                       # kept days occupy their slot already
        fam = _dish_family(c.get("recipe_name") or "")
        if fam:
            used_fam.setdefault(c["slot"], set()).add(fam)
        if c.get("recipe_id"):
            used_ids.setdefault(c["slot"], set()).add(c["recipe_id"])

    deduped: list[_PlannedMeal] = []
    freed_cells: list[tuple[int, str]] = []
    for meal in valid_meals:
        sc = slot_by_name[meal.slot]
        batch = sc.distinct_meals is not None and sc.distinct_meals > 0
        fams = used_fam.setdefault(meal.slot, set())
        ids = used_ids.setdefault(meal.slot, set())
        fam = _meal_family(meal)
        taken = (fam and fam in fams) or (meal.use_recipe_id and meal.use_recipe_id in ids)
        if not batch and taken:
            freed_cells.append((meal.day_offset, meal.slot))
            continue
        if fam:
            fams.add(fam)
        if meal.use_recipe_id:
            ids.add(meal.use_recipe_id)
        deduped.append(meal)

    # 3) Backfill freed days: unique saved dish OR lunchbox leftovers OR gen.
    leftover_sources = list(deduped)     # dishes actually cooked this week
    leftover_uses = [0] * len(leftover_sources)
    # Plan-wide recipe ids already placed (any slot) so backfill never reuses the
    # same recipe across two slots.
    placed_ids: set[str] = {m.use_recipe_id for m in deduped if m.use_recipe_id}
    placed_ids |= {c["recipe_id"] for c in kept if c.get("recipe_id")}

    def _pick_distinct_saved(slot: str, fams: set[str]):
        return next(
            (r for r in saved_rows
             if r["id"] not in placed_ids
             and _dish_family(r["name"]) not in fams
             and (not r["meal_type"] or r["meal_type"] == slot)),
            None,
        )

    def _next_leftover(slot: str) -> _PlannedMeal | None:
        # ONLY reuse genuinely lunchbox-friendly dishes — never make a soggy
        # taco/burger a "leftover".
        elig = [
            i for i, m in enumerate(leftover_sources)
            if m.lunchbox_friendly and m.slot == slot and leftover_uses[i] < 2
        ]
        if not elig:
            return None
        i = min(elig, key=lambda i: leftover_uses[i])
        leftover_uses[i] += 1
        src = leftover_sources[i]
        return _PlannedMeal(
            day_offset=0, slot=slot,
            use_recipe_id=src.use_recipe_id,
            new_recipe_prompt=src.new_recipe_prompt,
            dish_name=src.dish_name, lunchbox_friendly=True,
            reason="leftovers from earlier in the week",
        )

    # Distinct style hints for generated backfill. `friendly` marks dishes that
    # keep as lunchboxes, so a lunchbox week never generates tacos/burgers.
    _GEN_HINTS = [
        ("soup", "a comforting soup or stew", True),
        ("curry", "a fragrant curry", True),
        ("bowl", "a grain or rice bowl", True),
        ("pasta", "a baked or saucy pasta", True),
        ("roast", "a sheet-pan roast", True),
        ("chili", "a hearty chili", True),
        ("frittata", "a frittata or egg bake", True),
        ("stir", "a quick stir-fry", False),
        ("salad", "a substantial main salad", False),
        ("wrap", "a wrap or flatbread plate", False),
    ]
    gen_cursor = 0

    def _make_generated(slot: str, doff: int) -> _PlannedMeal:
        nonlocal gen_cursor
        fams = used_fam.setdefault(slot, set())
        hint = hint_fam = None
        for _ in range(len(_GEN_HINTS)):
            famword, text, friendly = _GEN_HINTS[gen_cursor % len(_GEN_HINTS)]
            gen_cursor += 1
            if lunchbox_mode and not friendly:
                continue
            if famword not in fams:
                hint, hint_fam = text, famword
                fams.add(famword)
                break
        if hint is not None and lunchbox_mode:
            prompt = (
                f"{hint.capitalize()} for {slot} — a batch-cook dish that reheats "
                f"and travels well as a lunchbox, fitting the brief ({brief}); "
                f"different from every other dish this week."
            )
        elif hint is not None:
            prompt = (
                f"{hint.capitalize()} for {slot}, fitting the brief ({brief}); "
                f"different from every other dish this week."
            )
        else:
            # styles exhausted — keep the prompt UNIQUE per day so it doesn't
            # dedup into one repeated dish.
            kind = "batch-cook lunchbox-friendly " if lunchbox_mode else ""
            prompt = (
                f"A distinct {kind}{slot} fitting the brief ({brief}), unlike any "
                f"other dish this week — variation for day {doff + 1}."
            )
        return _PlannedMeal(
            day_offset=doff, slot=slot, new_recipe_prompt=prompt,
            dish_name=hint_fam, lunchbox_friendly=lunchbox_mode,
            reason=("batch-cooked for lunchboxes" if lunchbox_mode
                    else "filling a day with a distinct dish"),
        )

    for doff, slot in freed_cells:
        fams = used_fam.setdefault(slot, set())
        placed: _PlannedMeal | None = None
        if lunchbox_mode:
            # Cook-once-eat-again: reuse a lunchbox-friendly dish, else GENERATE a
            # lunchbox-friendly one and add it to the pool so later days reuse it.
            lo = _next_leftover(slot)
            if lo:
                lo.day_offset = doff
                placed = lo
            else:
                placed = _make_generated(slot, doff)
                leftover_sources.append(placed)
                leftover_uses.append(0)
        else:
            pick = _pick_distinct_saved(slot, fams)
            if pick:
                placed_ids.add(pick["id"])
                pf = _dish_family(pick["name"])
                if pf:
                    fams.add(pf)
                placed = _PlannedMeal(day_offset=doff, slot=slot, use_recipe_id=pick["id"])
            if placed is None:
                lo = _next_leftover(slot)
                if lo:
                    lo.day_offset = doff
                    placed = lo
            if placed is None:
                placed = _make_generated(slot, doff)
        deduped.append(placed)

    # 4) Generation set + reasons from the final assignment.
    unique_prompts: list[str] = []
    seen: set[str] = set()
    prompt_to_reason: dict[str, str] = {}
    for meal in deduped:
        if meal.new_recipe_prompt and meal.new_recipe_prompt not in seen:
            seen.add(meal.new_recipe_prompt)
            unique_prompts.append(meal.new_recipe_prompt)
            prompt_to_reason[meal.new_recipe_prompt] = (meal.reason or "").strip()
    return deduped, unique_prompts, prompt_to_reason


async def _save_generated_recipe(conn, gen, household_id: str, servings: int) -> str:
    """Persist one generated recipe: insert it (+ valid ingredients), mirror to
    the public pool for Explore, and schedule an image. Returns the new recipe id.
    Shared by /generate and /regenerate."""
    from api.image_gen import schedule_image, schedule_pool_image
    from api.public_pool import mirror_to_pool

    recipe_row = await conn.fetchrow(
        """
        INSERT INTO hearth.recipes (household_id, name, instructions, servings)
        VALUES ($1::uuid, $2, $3::jsonb, $4)
        RETURNING id::text AS id
        """,
        household_id, gen.name, gen.instructions, servings,
    )
    rid = recipe_row["id"]
    # Dedup by fdc_id (LLM sometimes emits the same code twice).
    grams_by_fdc: dict[int, float] = {}
    for ing in gen.ingredients:
        grams_by_fdc[ing.fdc_id] = grams_by_fdc.get(ing.fdc_id, 0.0) + ing.quantity_g
    if grams_by_fdc:
        valid_rows = await conn.fetch(
            "SELECT fdc_id FROM hearth.usda_ingredients WHERE fdc_id = ANY($1::int[])",
            list(grams_by_fdc.keys()),
        )
        valid_set = {r["fdc_id"] for r in valid_rows}
        for fdc_id, qty in grams_by_fdc.items():
            if fdc_id in valid_set:
                await conn.execute(
                    "INSERT INTO hearth.recipe_ingredients (recipe_id, fdc_id, quantity_g) "
                    "VALUES ($1::uuid, $2, $3)",
                    rid, fdc_id, qty,
                )

    public_id = await mirror_to_pool(
        name=gen.name,
        ingredients=[{"fdc_id": i.fdc_id, "name": i.name, "quantity_g": i.quantity_g}
                     for i in gen.ingredients],
        instructions=gen.instructions,
        source="llm",
        originating_household_id=household_id,
    )
    if public_id:
        await conn.execute(
            "UPDATE hearth.recipes SET public_origin_id = $1::uuid WHERE id = $2::uuid",
            public_id, rid,
        )
        schedule_pool_image(public_id, gen.name)
    else:
        async with service_tx() as svc:
            pool_row = await svc.fetchrow(
                "SELECT id::text AS id, image_path FROM hearth.public_recipes "
                "WHERE lower(name) = lower($1)",
                gen.name,
            )
        if pool_row:
            await conn.execute(
                "UPDATE hearth.recipes SET public_origin_id = $1::uuid, "
                "image_path = COALESCE(image_path, $2) WHERE id = $3::uuid",
                pool_row["id"], pool_row["image_path"], rid,
            )
        if not pool_row or not pool_row["image_path"]:
            schedule_image(rid, gen.name, household_id)
    return rid


def _is_lunchbox_brief(brief_lc: str) -> bool:
    """Explicit lunchbox/batch intent in the brief. ('busy'/'work hard' were
    dropped — they over-triggered, turning ordinary weeks into leftover weeks.)"""
    return any(w in brief_lc for w in [
        "matlåd", "matlad", "batch", "meal prep", "mealprep", "lunchbox",
        "lunch box", "lunch-box", "leftover", "prep ahead", "prep-ahead",
    ])


def _planner_system_prompt(slot_rules: str, lunchbox_mode: bool) -> str:
    """The reuse-first / variety / lunchbox planner system prompt. Shared by
    /generate and /regenerate so both behave identically."""
    matlada_hint = ""
    if lunchbox_mode:
        matlada_hint = (
            "\n- LUNCHBOX / matlåda / batch-cooking week: plan FEWER distinct "
            "dishes, and choose ones that are genuinely lunchbox_friendly (stews, "
            "curries, chilis, pasta bakes, grain bowls, roasts, soups) so they can "
            "be eaten again as next-day leftovers. Do NOT build the week around "
            "tacos, burgers, fried or fresh dishes — they don't keep as lunchboxes."
        )
    return (
        "You are a weekly meal planner for a household that values REUSING the "
        "recipes it already has. You have search tools — use them before "
        "inventing anything.\n\n"
        f"Slots and their portions:\n{slot_rules}\n\n"
        "Fill ONLY the (day_offset, slot) cells the brief lists as available — "
        "one _PlannedMeal each. For every cell:\n"
        "  1. SEARCH FIRST: call search_recipes(query) for a saved recipe that "
        "     fits the brief and slot. These are creatures of habit — reusing a "
        "     recipe they've cooked before is the PREFERRED outcome, not a "
        "     compromise. Set use_recipe_id to the exact id.\n"
        "  2. If nothing saved fits, call search_pool_recipes(query) and reuse a "
        "     pool recipe by setting use_recipe_id to its public_recipe_id.\n"
        "  3. ONLY if neither search yields a fit, set new_recipe_prompt for a "
        "     fresh recipe AND set `reason` to a short why (e.g. 'no saved/pool "
        "     match', or 'user asked to try it').\n"
        "Generation costs a credit and clutters the library — last resort. A plan "
        "that reuses 5 saved recipes and generates 2 is BETTER than one that "
        "generates 7.\n\n"
        "Rules:\n"
        "- Each cell: EITHER use_recipe_id OR new_recipe_prompt — never both, "
        "  never neither.\n"
        "- Set `dish_name` on EVERY meal to its short FAMILY (1-2 words, "
        "  lowercase, no adjectives or proteins): tacos, burger, curry, stir "
        "  fry, pasta, salad, soup, etc.\n"
        "- Set `lunchbox_friendly` = true ONLY for dishes that genuinely reheat "
        "  and travel well as a next-day lunchbox: stews, curries, chili, pasta "
        "  bakes, grain/rice bowls, roasts, soups, casseroles. Set it FALSE for "
        "  tacos, burgers, sandwiches/wraps, anything crispy or fried, leafy "
        "  salads, and delicate fish — these go soggy and are NOT lunchboxes.\n"
        "- VARIETY: a `dish_name` family may appear on AT MOST ONE day of the "
        "  plan, UNLESS the user asked for batch-cooking / matlåda / leftovers. "
        "  'beef tacos' and 'fish tacos' are BOTH family 'tacos' — pick one and "
        "  move on. Week-to-week repeats are fine; the same family twice in ONE "
        "  plan is not.\n"
        "- NAMED DISHES = ONCE EACH: if the brief names dishes to 'try' (e.g. "
        "  'tacos and salmon burgers'), include EACH named dish on exactly ONE "
        "  day, then fill the REST of the days with DIFFERENT families. NEVER "
        "  theme the whole week around the named dishes, and never generate "
        "  several near-identical variants of one.\n"
        "- ALREADY ON THE CALENDAR: the brief may list meals already planned on "
        "  some days (kept). Do NOT plan those cells, and do NOT repeat those "
        "  dishes elsewhere in this plan.\n"
        "- To batch-cook a dish across multiple days in the same slot (only when "
        "  asked): emit one _PlannedMeal per day with the SAME use_recipe_id, or "
        "  an IDENTICAL new_recipe_prompt string (identical prompts dedup into "
        "  one recipe).\n"
        "- NEVER reuse the same recipe across different slots; breakfast, lunch "
        "  and dinner are disjoint dish sets.\n"
        "- SHARE INGREDIENTS across the week when reasonable to shorten the "
        "  shopping list — lean toward overlap; don't sacrifice the brief for it.\n"
        "- Honour dietary constraints (vegetarian, gluten-free, allergies) "
        "  strictly.\n"
        "- new_recipe_prompt should be evocative and specific, and match the "
        "  slot — breakfast prompts should be breakfast food.\n"
        "- day_offset is 0-indexed from the plan start.\n"
        "- The `portions` field on _PlannedMeal is advisory; the server overrides "
        "  it with the slot's configured portions.\n"
        "- plan_name should be evocative."
        + matlada_hint
    )


@router.post("/generate")
async def generate_meal_plan(
    body: GenerateMealPlanRequest,
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    """LLM-powered weekly plan generator — streams NDJSON progress events.

    Response is `application/x-ndjson`: one JSON object per line, terminated
    by `\\n`. Event types (the `type` field):

      planning_start    {"brief": "...", "days": 7, "slots": ["dinner"]}
      planning_done     {"meals_proposed": 7, "recipes_to_generate": 4,
                         "plan_name": "Spring Mediterranean"}
      recipe_start      {"prompt": "Lemon-Garlic Cod...", "reason": "no saved/pool match"}
      recipe_done       {"name": "Lemon-Garlic Cod...", "duration": 9.2}
      recipe_failed     {"prompt": "...", "error": "..."}
      persisting        {}
      complete          {"plan": <MealPlanOut>, "total_duration": 47.1}
      error             {"message": "..."}

    Frontend reads the stream, surfaces events live, and uses the `complete`
    event's `plan` as the final result.
    """
    from api.agent_core.context import ToolContext
    from api.agent_core.tools import _is_uuid, get_calendar_conflicts
    from api.agent_tools import build_planner_search_tools
    from api.credits import finalize_hold, hold, release_hold
    from api.profile import load_profile, render_profile_context
    from api.recipe_gen import generate_recipe

    # Validation + credit hold happen synchronously up front so 4xx errors
    # are normal HTTPExceptions (not mid-stream).
    if body.days < 1 or body.days > 14:
        raise HTTPException(400, "days must be 1..14")
    if not body.slot_configs:
        raise HTTPException(400, "slot_configs must not be empty")

    # Calendar-aware pre-flight: which (day_offset, slot) cells are free to plan?
    # Occupied cells the user did NOT mark for replacement are KEPT (skipped) so
    # we never double-book a day they'd already planned.
    ctx = ToolContext(user=user, household_id=household_id)
    slot_names = [sc.slot for sc in body.slot_configs]
    end_date = body.start_date + timedelta(days=body.days - 1)
    conflicts = await get_calendar_conflicts(
        ctx, body.start_date.isoformat(), end_date.isoformat(), slot_names
    )
    replace_set = set(body.replace_entry_ids)
    kept = [c for c in conflicts if c["entry_id"] not in replace_set]
    kept_cells = {
        ((date.fromisoformat(c["plan_date"]) - body.start_date).days, c["slot"])
        for c in kept
    }
    fillable_cells = [
        (d, sc.slot)
        for d in range(body.days)
        for sc in body.slot_configs
        if (d, sc.slot) not in kept_cells
    ]
    if not fillable_cells:
        raise HTTPException(
            400,
            "Every selected day is already planned. Mark a day Replace, or pick "
            "a different range.",
        )

    max_cost = 1.0 + float(len(fillable_cells))
    hold_id = await hold(household_id, "weekly_plan", max_cost)

    slot_by_name: dict[str, SlotConfig] = {sc.slot: sc for sc in body.slot_configs}

    # Build per-slot rules for the planner prompt.
    slot_rules_lines: list[str] = []
    for sc in body.slot_configs:
        line = f"  * {sc.slot}: portions={sc.portions}"
        if sc.distinct_meals is not None and sc.distinct_meals > 0:
            line += (
                f", HARD CAP of {sc.distinct_meals} distinct dishes across all "
                f"{body.days} days (batch-cook / matlåda style — each dish repeats)"
            )
        slot_rules_lines.append(line)
    slot_rules = "\n".join(slot_rules_lines)

    brief_lc = body.prompt.lower()
    # Explicit lunchbox intent only — "busy"/"work hard" over-triggered, turning
    # ordinary weeks into leftover weeks.
    lunchbox_mode = _is_lunchbox_brief(brief_lc)

    cells_lines = "\n".join(f"  - day_offset={d}, slot={s}" for d, s in fillable_cells)
    if kept:
        kept_lines = "\n".join(
            f"  - day_offset={(date.fromisoformat(c['plan_date']) - body.start_date).days}, "
            f"slot={c['slot']}: {c['recipe_name']}"
            for c in kept
        )
        kept_block = (
            "\n\nAlready on the calendar — KEEP (do NOT plan these cells, do NOT "
            f"repeat these dishes elsewhere in the plan):\n{kept_lines}"
        )
    else:
        kept_block = ""

    planner_system_prompt = _planner_system_prompt(slot_rules, lunchbox_mode)

    async def event_stream():
        def emit(event_type: str, **data) -> str:
            return json.dumps({"type": event_type, **data}) + "\n"

        overall_start = time.monotonic()
        log.warning("[plan-gen] stream starting (prompt=%r, days=%d)",
                    body.prompt[:60], body.days)

        # ---- Stage 1: planner ----
        try:
            yield emit(
                "planning_start",
                brief=body.prompt[:140],
                days=body.days,
                slots=[sc.slot for sc in body.slot_configs],
            )

            planner = Agent(
                _PLAN_MODEL,
                output_type=_PlannedWeek,
                system_prompt=planner_system_prompt,
                tools=build_planner_search_tools(ctx),
            )

            async with user_tx(user) as conn:
                existing_recipes_listing = await _list_existing_recipes_for_planner(conn)
            profile_block = render_profile_context(await load_profile(household_id))

            user_brief = (
                f"Brief: {body.prompt}\n\n"
                f"Base servings per generated recipe: {body.servings}\n\n"
                f"Fill EXACTLY these cells (one _PlannedMeal each):\n{cells_lines}"
                f"{kept_block}\n\n"
                f"--- Household profile ---\n{profile_block}\n\n"
                f"Respect the household profile strictly: never include allergens, "
                f"avoid dislikes, lean into likes/cuisines.\n\n"
                f"Some saved recipes (also use the search tools to find more, and "
                f"prefer reusing these over generating):\n{existing_recipes_listing}"
            )

            planner_start = time.monotonic()
            planned = (await planner.run(user_brief)).output
            log.warning(
                "[plan-gen] planner done in %.1fs — %d meals proposed",
                time.monotonic() - planner_start, len(planned.meals),
            )
        except Exception as e:
            log.exception("[plan-gen] planner failed")
            try: await release_hold(hold_id)
            except Exception: log.exception("[plan-gen] release_hold failed")
            yield emit("error", message=f"Plan generation failed: {e}")
            return

        # Dedup + slot-disjoint validation of planner output. Pull saved recipes
        # ranked reuse-first (most-cooked, then Explore-liked) so we can backfill
        # any day the planner duplicated a dish onto.
        async with user_tx(user) as conn:
            saved_rows = await conn.fetch(
                """
                SELECT r.id::text AS id, r.name, r.meal_type,
                       COALESCE(p.times_planned, 0) AS tp,
                       (r.public_origin_id IS NOT NULL) AS fe
                FROM hearth.recipes r
                LEFT JOIN (
                    SELECT recipe_id, COUNT(*)::int AS times_planned
                    FROM hearth.meal_plan_entries GROUP BY recipe_id
                ) p ON p.recipe_id = r.id
                ORDER BY tp DESC, fe DESC, r.updated_at DESC
                """
            )
        valid_ids = {r["id"] for r in saved_rows}

        valid_meals, unique_prompts, prompt_to_reason = _assemble_week(
            planned.meals,
            saved_rows=saved_rows,
            kept=kept,
            kept_cells=kept_cells,
            slot_by_name=slot_by_name,
            days=body.days,
            lunchbox_mode=lunchbox_mode,
            brief=body.prompt,
        )

        yield emit(
            "planning_done",
            meals_proposed=len(valid_meals),
            recipes_to_generate=len(unique_prompts),
            plan_name=planned.plan_name,
        )

        # ---- Stage 2: recipe gens (parallel, with per-recipe live events) ----
        concurrency = int(os.getenv("RECIPE_GEN_CONCURRENCY", "3"))
        sem = asyncio.Semaphore(concurrency)
        event_queue: asyncio.Queue = asyncio.Queue()

        async def gen_one(prompt: str, reason: str):
            async with sem:
                t0 = time.monotonic()
                await event_queue.put({
                    "type": "recipe_start", "prompt": prompt[:100],
                    "reason": reason or "no saved/pool match",
                })
                log.warning("[plan-gen] generating recipe: %r", prompt[:80])
                try:
                    gen = await generate_recipe(prompt)
                    duration = round(time.monotonic() - t0, 1)
                    log.warning("[plan-gen]   → '%s' in %.1fs", gen.name, duration)
                    await event_queue.put({
                        "type": "recipe_done", "name": gen.name,
                        "duration": duration,
                    })
                    return prompt, gen
                except Exception as e:
                    duration = round(time.monotonic() - t0, 1)
                    log.warning("[plan-gen]   FAILED in %.1fs: %s", duration, e)
                    await event_queue.put({
                        "type": "recipe_failed", "prompt": prompt[:100],
                        "error": str(e),
                    })
                    return prompt, None

        tasks = [
            asyncio.create_task(gen_one(p, prompt_to_reason.get(p, "")))
            for p in unique_prompts
        ]

        # Drain the queue: each task pushes a recipe_start AND a terminal
        # (recipe_done OR recipe_failed). Loop ends when every task has
        # emitted its terminal event.
        finished = 0
        target = len(tasks)
        while finished < target:
            ev = await event_queue.get()
            ev_type = ev["type"]
            payload = {k: v for k, v in ev.items() if k != "type"}
            yield emit(ev_type, **payload)
            if ev_type in ("recipe_done", "recipe_failed"):
                finished += 1

        # Tasks are guaranteed complete now (their last action is the terminal
        # push above), so gather is essentially synchronous — just collects
        # the (prompt, gen) return values.
        results: list = await asyncio.gather(*tasks) if tasks else []

        # ---- Stage 3: persist plan + new recipes + entries ----
        try:
            yield emit("persisting")

            # The planner is told to reuse pool recipes by setting use_recipe_id
            # to a public_recipe_id. Those aren't in the household's saved recipes,
            # so import each referenced pool recipe once (free, no LLM credit) and
            # remember the local id — otherwise the day would be dropped at insert.
            from api.public_pool import copy_to_household
            pool_to_local: dict[str, str] = {}
            for meal in valid_meals:
                pid = meal.use_recipe_id
                if pid and _is_uuid(pid) and pid not in valid_ids and pid not in pool_to_local:
                    local, _name = await copy_to_household(pid, household_id)
                    if local:
                        pool_to_local[pid] = local
                        valid_ids.add(local)

            prompt_to_recipe_id: dict[str, str] = {}
            async with user_tx(user) as conn:
                plan_row = await conn.fetchrow(
                    """
                    INSERT INTO hearth.meal_plans (household_id, name, start_date)
                    VALUES ($1::uuid, $2, $3::date)
                    RETURNING id::text AS id
                    """,
                    household_id, planned.plan_name, body.start_date,
                )
                plan_id = plan_row["id"]

                # Replace: drop the old meals the user chose to overwrite. Bounded
                # to entries we actually detected as conflicts in this range.
                replace_ids = [c["entry_id"] for c in conflicts if c["entry_id"] in replace_set]
                if replace_ids:
                    await conn.execute(
                        "DELETE FROM hearth.meal_plan_entries WHERE id = ANY($1::uuid[])",
                        replace_ids,
                    )

                for prompt, gen in results:
                    if gen is None:
                        continue
                    prompt_to_recipe_id[prompt] = await _save_generated_recipe(
                        conn, gen, household_id, body.servings
                    )

                # Fallback so a day is never silently blanked when its recipe
                # can't be resolved (pool import miss / failed generation): grab an
                # unused saved recipe, reuse-first. Seed "used" with every planned
                # saved/pool id so the fallback doesn't collide with an intended dish.
                used_recipe_ids: set[str] = {
                    pool_to_local.get(m.use_recipe_id, m.use_recipe_id)
                    for m in valid_meals if m.use_recipe_id
                }
                def _fallback_recipe(slot: str) -> str | None:
                    # Prefer a slot-appropriate unused saved recipe (untagged or
                    # matching meal_type) — never put a breakfast recipe at dinner.
                    for r in saved_rows:
                        if r["id"] not in used_recipe_ids and (
                            not r["meal_type"] or r["meal_type"] == slot
                        ):
                            return r["id"]
                    return None

                dropped = 0
                for meal in valid_meals:
                    recipe_id: str | None = None
                    if meal.use_recipe_id:
                        rid = pool_to_local.get(meal.use_recipe_id, meal.use_recipe_id)
                        if rid in valid_ids:
                            recipe_id = rid
                    if recipe_id is None and meal.new_recipe_prompt:
                        recipe_id = prompt_to_recipe_id.get(meal.new_recipe_prompt)
                    if recipe_id is None:
                        recipe_id = _fallback_recipe(meal.slot)
                    if not recipe_id:
                        dropped += 1
                        continue
                    used_recipe_ids.add(recipe_id)

                    plan_date = body.start_date + timedelta(days=meal.day_offset)

                    slot_cfg = slot_by_name.get(meal.slot)
                    portions = float(slot_cfg.portions) if slot_cfg else float(meal.portions)
                    await conn.execute(
                        """
                        INSERT INTO hearth.meal_plan_entries
                            (household_id, meal_plan_id, recipe_id, plan_date, slot, portions)
                        VALUES ($1::uuid, $2::uuid, $3::uuid, $4::date, $5, $6)
                        """,
                        household_id, plan_id, recipe_id, plan_date, meal.slot, max(0.25, portions),
                    )

                out = await _build_plan_out(conn, plan_id)
            if dropped:
                log.warning("[plan-gen] %d planned day(s) could not be filled "
                            "(empty library + failed generation)", dropped)
        except Exception as e:
            log.exception("[plan-gen] persist failed")
            try: await release_hold(hold_id)
            except Exception: pass
            yield emit("error", message=f"Saving the plan failed: {e}")
            return

        total_duration = round(time.monotonic() - overall_start, 1)
        log.warning(
            "[plan-gen] DONE in %.1fs — plan '%s' with %d entries",
            total_duration, out.name, len(out.entries),
        )

        actual_recipes = len([1 for _, g in results if g is not None])
        actual_cost = 1.0 + float(actual_recipes)
        await finalize_hold(hold_id, actual_cost)

        # Final event with the saved plan as the payload.
        # model_dump(mode='json') turns datetimes/UUIDs into ISO/string.
        yield emit(
            "complete",
            plan=out.model_dump(mode="json"),
            total_duration=total_duration,
        )

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


class RegenerateRequest(BaseModel):
    flagged_entry_ids: list[str]
    prompt: str = ""
    servings: int = 4


@router.post("/{plan_id}/regenerate", response_model=MealPlanOut)
async def regenerate_meal_plan(
    plan_id: str,
    body: RegenerateRequest,
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    """Re-roll the flagged days of an existing plan, keeping the rest. Kept meals
    are honoured for variety (their families/ids won't be repeated), and reuse-
    first + lunchbox rules apply exactly as in the wizard. Non-streaming — the
    user flags only a few days — returns the updated plan."""
    from api.agent_core.context import ToolContext
    from api.agent_core.tools import _is_uuid
    from api.agent_tools import build_planner_search_tools
    from api.credits import finalize_hold, hold, release_hold
    from api.profile import load_profile, render_profile_context
    from api.public_pool import copy_to_household
    from api.recipe_gen import generate_recipe

    flagged_set = {e for e in body.flagged_entry_ids if _is_uuid(e)}

    async with user_tx(user) as conn:
        plan = await conn.fetchrow(
            "SELECT start_date FROM hearth.meal_plans WHERE id = $1::uuid", plan_id
        )
        if plan is None:
            raise HTTPException(404, "Meal plan not found")
        start_date = plan["start_date"]
        entries = await conn.fetch(
            """
            SELECT e.id::text AS entry_id, e.plan_date, e.slot, e.portions,
                   e.recipe_id::text AS recipe_id, r.name AS recipe_name
            FROM hearth.meal_plan_entries e
            LEFT JOIN hearth.recipes r ON r.id = e.recipe_id
            WHERE e.meal_plan_id = $1::uuid
            ORDER BY e.plan_date, e.slot
            """,
            plan_id,
        )

    flagged = [e for e in entries if e["entry_id"] in flagged_set]
    if not flagged:
        async with user_tx(user) as conn:
            return await _build_plan_out(conn, plan_id)
    kept_entries = [e for e in entries if e["entry_id"] not in flagged_set]

    def _doff(d) -> int:
        return (d - start_date).days

    days = max(_doff(e["plan_date"]) for e in entries) + 1
    fillable_cells = [(_doff(e["plan_date"]), e["slot"]) for e in flagged]
    kept_cells = {(_doff(e["plan_date"]), e["slot"]) for e in kept_entries}
    kept = [
        {"slot": e["slot"], "recipe_id": e["recipe_id"],
         "recipe_name": e["recipe_name"], "plan_date": e["plan_date"].isoformat()}
        for e in kept_entries
    ]
    slot_by_name: dict[str, SlotConfig] = {}
    for e in flagged:
        slot_by_name.setdefault(e["slot"], SlotConfig(slot=e["slot"], portions=float(e["portions"])))

    lunchbox_mode = _is_lunchbox_brief(body.prompt.lower())
    hold_id = await hold(household_id, "weekly_plan", float(len(fillable_cells)))

    try:
        ctx = ToolContext(user=user, household_id=household_id)
        slot_rules = "\n".join(
            f"  * {s}: portions={sc.portions}" for s, sc in slot_by_name.items()
        )
        planner = Agent(
            _PLAN_MODEL, output_type=_PlannedWeek,
            system_prompt=_planner_system_prompt(slot_rules, lunchbox_mode),
            tools=build_planner_search_tools(ctx),
        )
        cells_lines = "\n".join(f"  - day_offset={d}, slot={s}" for d, s in fillable_cells)
        kept_lines = "\n".join(
            f"  - day_offset={_doff(date.fromisoformat(c['plan_date']))}, "
            f"slot={c['slot']}: {c['recipe_name']}"
            for c in kept
        )
        kept_block = (
            "\n\nAlready on the calendar — KEEP (do NOT plan these cells, do NOT "
            f"repeat these dishes):\n{kept_lines}" if kept else ""
        )
        async with user_tx(user) as conn:
            existing_recipes_listing = await _list_existing_recipes_for_planner(conn)
        profile_block = render_profile_context(await load_profile(household_id))
        user_brief = (
            f"Brief: {body.prompt or 'replace the flagged days with different dishes the household will like'}\n\n"
            f"Base servings per generated recipe: {body.servings}\n\n"
            f"The user DISLIKED the dishes currently on these cells — replace each "
            f"with a DIFFERENT dish (different family). Fill EXACTLY these cells:\n"
            f"{cells_lines}{kept_block}\n\n"
            f"--- Household profile ---\n{profile_block}\n\n"
            f"Respect the household profile strictly.\n\n"
            f"Some saved recipes (prefer reusing these):\n{existing_recipes_listing}"
        )
        planned = (await planner.run(user_brief)).output

        async with user_tx(user) as conn:
            saved_rows = await conn.fetch(
                """
                SELECT r.id::text AS id, r.name, r.meal_type,
                       COALESCE(p.times_planned, 0) AS tp,
                       (r.public_origin_id IS NOT NULL) AS fe
                FROM hearth.recipes r
                LEFT JOIN (
                    SELECT recipe_id, COUNT(*)::int AS times_planned
                    FROM hearth.meal_plan_entries GROUP BY recipe_id
                ) p ON p.recipe_id = r.id
                ORDER BY tp DESC, fe DESC, r.updated_at DESC
                """
            )
        valid_ids = {r["id"] for r in saved_rows}

        valid_meals, unique_prompts, _ = _assemble_week(
            planned.meals, saved_rows=saved_rows, kept=kept, kept_cells=kept_cells,
            slot_by_name=slot_by_name, days=days, lunchbox_mode=lunchbox_mode,
            brief=body.prompt,
        )

        async def _gen(p: str):
            try:
                return p, await generate_recipe(p)
            except Exception:
                log.exception("[regen] recipe generation failed for %r", p[:60])
                return p, None

        results = await asyncio.gather(*[_gen(p) for p in unique_prompts]) if unique_prompts else []

        pool_to_local: dict[str, str] = {}
        for meal in valid_meals:
            pid = meal.use_recipe_id
            if pid and _is_uuid(pid) and pid not in valid_ids and pid not in pool_to_local:
                local, _name = await copy_to_household(pid, household_id)
                if local:
                    pool_to_local[pid] = local
                    valid_ids.add(local)

        async with user_tx(user) as conn:
            prompt_to_recipe_id: dict[str, str] = {}
            for prompt, gen in results:
                if gen is not None:
                    prompt_to_recipe_id[prompt] = await _save_generated_recipe(
                        conn, gen, household_id, body.servings
                    )
            # Replace: delete the flagged entries, then insert the new ones.
            await conn.execute(
                "DELETE FROM hearth.meal_plan_entries WHERE id = ANY($1::uuid[])",
                list(flagged_set),
            )
            used_recipe_ids: set[str] = {
                pool_to_local.get(m.use_recipe_id, m.use_recipe_id)
                for m in valid_meals if m.use_recipe_id
            }
            used_recipe_ids |= {e["recipe_id"] for e in kept_entries if e["recipe_id"]}

            def _fallback_recipe(slot: str) -> str | None:
                for r in saved_rows:
                    if r["id"] not in used_recipe_ids and (
                        not r["meal_type"] or r["meal_type"] == slot
                    ):
                        return r["id"]
                return None

            for meal in valid_meals:
                recipe_id: str | None = None
                if meal.use_recipe_id:
                    rid = pool_to_local.get(meal.use_recipe_id, meal.use_recipe_id)
                    if rid in valid_ids:
                        recipe_id = rid
                if recipe_id is None and meal.new_recipe_prompt:
                    recipe_id = prompt_to_recipe_id.get(meal.new_recipe_prompt)
                if recipe_id is None:
                    recipe_id = _fallback_recipe(meal.slot)
                if not recipe_id:
                    continue
                used_recipe_ids.add(recipe_id)
                plan_date = start_date + timedelta(days=meal.day_offset)
                slot_cfg = slot_by_name.get(meal.slot)
                portions = float(slot_cfg.portions) if slot_cfg else float(meal.portions)
                await conn.execute(
                    """
                    INSERT INTO hearth.meal_plan_entries
                        (household_id, meal_plan_id, recipe_id, plan_date, slot, portions)
                    VALUES ($1::uuid, $2::uuid, $3::uuid, $4::date, $5, $6)
                    """,
                    household_id, plan_id, recipe_id, plan_date, meal.slot, max(0.25, portions),
                )
            out = await _build_plan_out(conn, plan_id)
    except HTTPException:
        try: await release_hold(hold_id)
        except Exception: pass
        raise
    except Exception as e:
        log.exception("[regen] failed")
        try: await release_hold(hold_id)
        except Exception: pass
        raise HTTPException(500, f"Regeneration failed: {e}")

    actual = len([1 for _, g in results if g is not None])
    await finalize_hold(hold_id, 1.0 + float(actual))
    return out


@router.post("/{plan_id}/shopping-list", response_model=ShoppingListOut)
async def shopping_list_from_plan(
    plan_id: str,
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
    include_template: bool = True,
):
    """Consolidate all entries in a plan into a single shopping list."""
    from api.shopping import generate_shopping_list

    async with user_tx(user) as conn:
        await _ensure_plan_visible(conn, plan_id)
        entries = await conn.fetch(
            "SELECT recipe_id::text AS recipe_id, portions "
            "FROM hearth.meal_plan_entries WHERE meal_plan_id = $1::uuid",
            plan_id,
        )

    totals: dict[str, float] = {}
    for e in entries:
        totals[e["recipe_id"]] = totals.get(e["recipe_id"], 0) + float(e["portions"])

    selections = [
        ShoppingRecipeSelection(recipe_id=rid, portions=pts)
        for rid, pts in totals.items()
    ]
    return await generate_shopping_list(
        selections,
        user=user,
        household_id=household_id,
        include_template=include_template,
    )
