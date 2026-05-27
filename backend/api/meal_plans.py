"""Meal plan CRUD + shopping list generation from a plan + AI weekly generator
(Postgres-backed, RLS-scoped per household)."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import asyncpg
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pydantic_ai import Agent

from api.auth import CurrentUser, get_current_user
from api.db import get_current_household_id, user_tx
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
    await conn.execute(
        "DELETE FROM hearth.meal_plan_entries WHERE meal_plan_id = $1::uuid",
        plan_id,
    )
    for e in entries:
        await conn.execute(
            """
            INSERT INTO hearth.meal_plan_entries
                (meal_plan_id, recipe_id, plan_date, slot, portions)
            VALUES ($1::uuid, $2::uuid, $3::date, $4, $5)
            """,
            plan_id, e.recipe_id, e.plan_date, e.slot, e.portions,
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
    start_date: str
    days: int = 7
    servings: int = 4
    slot_configs: list[SlotConfig] = [SlotConfig(slot="dinner")]


class _PlannedMeal(BaseModel):
    day_offset: int
    slot: str
    use_recipe_id: str | None = None
    new_recipe_prompt: str | None = None
    portions: float = 1


class _PlannedWeek(BaseModel):
    plan_name: str
    meals: list[_PlannedMeal]


_PLAN_MODEL = os.getenv("OPENAI_RECIPE_MODEL", "openai:gpt-4o")


@router.post("/generate", response_model=MealPlanOut)
async def generate_meal_plan(
    body: GenerateMealPlanRequest,
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    """LLM-powered weekly plan generator (Postgres-backed)."""
    from api.credits import finalize_hold, hold, release_hold
    from api.image_gen import schedule_image
    from api.profile import load_profile, render_profile_context
    from api.recipe_gen import generate_recipe

    if body.days < 1 or body.days > 14:
        raise HTTPException(400, "days must be 1..14")
    if not body.slot_configs:
        raise HTTPException(400, "slot_configs must not be empty")

    max_cost = 1.0 + float(body.days * len(body.slot_configs))
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

    matlada_hint = ""
    brief_lc = body.prompt.lower()
    if any(w in brief_lc for w in ["matlåd", "matlad", "batch", "meal prep", "work hard", "busy"]):
        matlada_hint = (
            "\n- The user wants a matlåda / batch-cooking style week. Default to "
            "2–3 distinct dishes per slot cooked in bigger portions, each eaten "
            "across 2–4 days. Don't design 7 unique dinners for a busy household."
        )

    planner_system_prompt = (
        "You are a weekly meal planner. Given a user brief and the household's "
        "existing saved recipes, design a coherent meal plan for the requested "
        "days and slots.\n\n"
        f"Slots to fill (one _PlannedMeal per slot per day):\n{slot_rules}\n\n"
        "Rules:\n"
        "- For each slot you fill, EITHER set use_recipe_id to one of the listed "
        "  saved recipes (use the exact id), OR set new_recipe_prompt to a short "
        "  description for a new recipe to be generated. Never both, never neither.\n"
        "- NEVER reuse the same recipe across different slots. Breakfast, lunch "
        "  and dinner must be disjoint sets of dishes.\n"
        "- To batch-cook a dish across multiple days in the same slot: emit one "
        "  _PlannedMeal per day with the SAME use_recipe_id (or an IDENTICAL "
        "  new_recipe_prompt string — identical prompts dedup into one recipe).\n"
        "- Reuse existing recipes when they fit the brief. Variety matters: avoid "
        "  the same protein two days in a row UNLESS the user asked for batch "
        "  cooking / matlåda / meal prep.\n"
        "- Honour dietary constraints (vegetarian, gluten-free, etc.) the user "
        "  states in the brief.\n"
        "- new_recipe_prompt should be evocative and specific. Match the meal "
        "  to the slot — breakfast prompts should be breakfast food.\n"
        "- day_offset is 0-indexed.\n"
        "- The `portions` field on _PlannedMeal is advisory; the server overrides "
        "  with the slot's configured portions.\n"
        "- plan_name should be evocative."
        + matlada_hint
    )

    planner = Agent(_PLAN_MODEL, output_type=_PlannedWeek, system_prompt=planner_system_prompt)

    # Read the household profile and existing recipes inside one transaction.
    async with user_tx(user) as conn:
        existing_recipes_listing = await _list_existing_recipes_for_planner(conn)

    profile_block = render_profile_context(await load_profile(household_id))

    user_brief = (
        f"Brief: {body.prompt}\n\n"
        f"Days: {body.days}\n"
        f"Base servings per generated recipe: {body.servings}\n"
        f"Slots are listed in the system prompt above.\n\n"
        f"--- Household profile ---\n{profile_block}\n\n"
        f"Respect the household profile strictly: never include allergens, avoid "
        f"dislikes, lean into likes/cuisines.\n\n"
        f"Existing saved recipes:\n{existing_recipes_listing}"
    )

    overall_start = time.monotonic()
    log.warning("[plan-gen] stage 1 planner starting (prompt=%r, days=%d)",
                body.prompt[:60], body.days)

    try:
        planner_start = time.monotonic()
        planned = (await planner.run(user_brief)).output
        log.warning(
            "[plan-gen] stage 1 planner done in %.1fs — %d meals proposed",
            time.monotonic() - planner_start, len(planned.meals),
        )
    except Exception as e:
        log.exception("[plan-gen] planner failed")
        try:
            await release_hold(hold_id)
        except Exception:
            log.exception("[plan-gen] hold release failed (continuing)")
        raise HTTPException(500, f"Plan generation failed: {e}")

    # Look up valid existing recipe ids (RLS-scoped).
    async with user_tx(user) as conn:
        rows = await conn.fetch("SELECT id::text AS id FROM hearth.recipes")
        valid_ids = {r["id"] for r in rows}

    valid_meals: list[_PlannedMeal] = []
    unique_prompts: list[str] = []
    seen_prompts: set[str] = set()
    prompt_to_slot: dict[str, str] = {}
    recipe_id_to_slot: dict[str, str] = {}
    for meal in planned.meals:
        if meal.day_offset < 0 or meal.day_offset >= body.days:
            continue
        if meal.slot not in slot_by_name:
            continue
        if not meal.use_recipe_id and not meal.new_recipe_prompt:
            continue
        if meal.use_recipe_id:
            prior = recipe_id_to_slot.get(meal.use_recipe_id)
            if prior and prior != meal.slot:
                log.warning("[plan-gen] dropping cross-slot reuse of %s",
                            meal.use_recipe_id)
                continue
            recipe_id_to_slot[meal.use_recipe_id] = meal.slot
        if meal.new_recipe_prompt:
            prior = prompt_to_slot.get(meal.new_recipe_prompt)
            if prior and prior != meal.slot:
                continue
            prompt_to_slot[meal.new_recipe_prompt] = meal.slot

        valid_meals.append(meal)
        if meal.new_recipe_prompt and meal.new_recipe_prompt not in seen_prompts:
            seen_prompts.add(meal.new_recipe_prompt)
            unique_prompts.append(meal.new_recipe_prompt)

    # Stage 2: generate all needed recipes concurrently (bounded by semaphore).
    concurrency = int(os.getenv("RECIPE_GEN_CONCURRENCY", "3"))
    sem = asyncio.Semaphore(concurrency)

    async def gen_one(prompt: str):
        async with sem:
            t0 = time.monotonic()
            log.warning("[plan-gen] generating recipe: %r", prompt[:80])
            try:
                gen = await generate_recipe(prompt)
                log.warning(
                    "[plan-gen]   → '%s' in %.1fs", gen.name, time.monotonic() - t0,
                )
                return prompt, gen
            except Exception as e:
                log.warning("[plan-gen]   FAILED in %.1fs: %s", time.monotonic() - t0, e)
                return prompt, None

    if unique_prompts:
        log.warning(
            "[plan-gen] stage 2: generating %d unique recipes (concurrency=%d)",
            len(unique_prompts), concurrency,
        )
        results = await asyncio.gather(*(gen_one(p) for p in unique_prompts))
    else:
        results = []

    # Persist the plan + new recipes + entries inside a single RLS-scoped tx.
    prompt_to_recipe_id: dict[str, str] = {}
    try:
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

            for prompt, gen in results:
                if gen is None:
                    continue
                # Use $N::jsonb for instructions
                recipe_row = await conn.fetchrow(
                    """
                    INSERT INTO hearth.recipes
                        (household_id, name, instructions, servings)
                    VALUES ($1::uuid, $2, $3::jsonb, $4)
                    RETURNING id::text AS id
                    """,
                    household_id, gen.name, gen.instructions, body.servings,
                )
                rid = recipe_row["id"]
                for ing in gen.ingredients:
                    await conn.execute(
                        "INSERT INTO hearth.recipe_ingredients "
                        "(recipe_id, fdc_id, quantity_g) "
                        "VALUES ($1::uuid, $2, $3)",
                        rid, ing.fdc_id, ing.quantity_g,
                    )
                prompt_to_recipe_id[prompt] = rid
                # Image gen runs detached (service_tx inside).
                schedule_image(rid, gen.name, household_id)

            for meal in valid_meals:
                recipe_id: str | None = None
                if meal.use_recipe_id and meal.use_recipe_id in valid_ids:
                    recipe_id = meal.use_recipe_id
                elif meal.new_recipe_prompt:
                    recipe_id = prompt_to_recipe_id.get(meal.new_recipe_prompt)
                if not recipe_id:
                    continue

                plan_date = (
                    datetime.fromisoformat(body.start_date)
                    + timedelta(days=meal.day_offset)
                ).strftime("%Y-%m-%d")

                slot_cfg = slot_by_name.get(meal.slot)
                portions = float(slot_cfg.portions) if slot_cfg else float(meal.portions)
                await conn.execute(
                    """
                    INSERT INTO hearth.meal_plan_entries
                        (meal_plan_id, recipe_id, plan_date, slot, portions)
                    VALUES ($1::uuid, $2::uuid, $3::date, $4, $5)
                    """,
                    plan_id, recipe_id, plan_date, meal.slot, max(0.25, portions),
                )

            out = await _build_plan_out(conn, plan_id)
    except Exception:
        try:
            await release_hold(hold_id)
        except Exception:
            log.exception("[plan-gen] hold release on persist failure failed")
        raise

    log.warning(
        "[plan-gen] DONE in %.1fs total — plan '%s' with %d entries",
        time.monotonic() - overall_start, out.name, len(out.entries),
    )

    actual_recipes = len([1 for _, g in results if g is not None])
    actual_cost = 1.0 + float(actual_recipes)
    await finalize_hold(hold_id, actual_cost)

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
