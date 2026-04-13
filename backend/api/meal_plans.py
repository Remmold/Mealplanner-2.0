"""Meal plan CRUD + shopping list generation from a plan + AI weekly generator."""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("mealplan.generate")

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pydantic_ai import Agent

from api.models import (
    MealPlanCreate,
    MealPlanEntryOut,
    MealPlanOut,
    MealPlanUpdate,
    ShoppingListOut,
)
from api.recipe_db import DEFAULT_HOUSEHOLD_ID, get_recipe_db, new_id
from api.shopping import generate_shopping_list
from api.models import ShoppingRecipeSelection

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

router = APIRouter(prefix="/meal-plans", tags=["meal-plans"])


def _build_plan_out(conn, plan_id: str) -> MealPlanOut:
    row = conn.execute("SELECT * FROM meal_plans WHERE id = ?", [plan_id]).fetchone()
    if not row:
        raise HTTPException(404, "Meal plan not found")

    entries = conn.execute(
        "SELECT e.id, e.recipe_id, e.plan_date, e.slot, e.portions, r.name AS recipe_name "
        "FROM meal_plan_entries e "
        "LEFT JOIN recipes r ON r.id = e.recipe_id "
        "WHERE e.meal_plan_id = ? "
        "ORDER BY e.plan_date, e.slot",
        [plan_id],
    ).fetchall()

    return MealPlanOut(
        id=row["id"],
        household_id=row["household_id"],
        name=row["name"],
        start_date=row["start_date"],
        entries=[
            MealPlanEntryOut(
                id=e["id"],
                recipe_id=e["recipe_id"],
                recipe_name=e["recipe_name"],
                plan_date=e["plan_date"],
                slot=e["slot"],
                portions=e["portions"],
            )
            for e in entries
        ],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _replace_entries(conn, plan_id: str, entries):
    conn.execute("DELETE FROM meal_plan_entries WHERE meal_plan_id = ?", [plan_id])
    for e in entries:
        conn.execute(
            "INSERT INTO meal_plan_entries (id, meal_plan_id, recipe_id, plan_date, slot, portions) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [new_id(), plan_id, e.recipe_id, e.plan_date, e.slot, e.portions],
        )


@router.get("", response_model=list[MealPlanOut])
def list_meal_plans(household_id: str = DEFAULT_HOUSEHOLD_ID):
    with get_recipe_db() as conn:
        rows = conn.execute(
            "SELECT id FROM meal_plans WHERE household_id = ? ORDER BY start_date DESC",
            [household_id],
        ).fetchall()
        return [_build_plan_out(conn, r["id"]) for r in rows]


@router.post("", response_model=MealPlanOut, status_code=201)
def create_meal_plan(body: MealPlanCreate, household_id: str = DEFAULT_HOUSEHOLD_ID):
    plan_id = new_id()
    with get_recipe_db() as conn:
        conn.execute(
            "INSERT INTO meal_plans (id, household_id, name, start_date) VALUES (?, ?, ?, ?)",
            [plan_id, household_id, body.name, body.start_date],
        )
        _replace_entries(conn, plan_id, body.entries)
        return _build_plan_out(conn, plan_id)


@router.get("/{plan_id}", response_model=MealPlanOut)
def get_meal_plan(plan_id: str):
    with get_recipe_db() as conn:
        return _build_plan_out(conn, plan_id)


@router.put("/{plan_id}", response_model=MealPlanOut)
def update_meal_plan(plan_id: str, body: MealPlanUpdate):
    with get_recipe_db() as conn:
        existing = conn.execute("SELECT id FROM meal_plans WHERE id = ?", [plan_id]).fetchone()
        if not existing:
            raise HTTPException(404, "Meal plan not found")

        if body.name is not None:
            conn.execute(
                "UPDATE meal_plans SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                [body.name, plan_id],
            )
        if body.start_date is not None:
            conn.execute(
                "UPDATE meal_plans SET start_date = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                [body.start_date, plan_id],
            )
        if body.entries is not None:
            _replace_entries(conn, plan_id, body.entries)
            conn.execute(
                "UPDATE meal_plans SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                [plan_id],
            )

        return _build_plan_out(conn, plan_id)


@router.delete("/{plan_id}", status_code=204)
def delete_meal_plan(plan_id: str):
    with get_recipe_db() as conn:
        existing = conn.execute("SELECT id FROM meal_plans WHERE id = ?", [plan_id]).fetchone()
        if not existing:
            raise HTTPException(404, "Meal plan not found")
        conn.execute("DELETE FROM meal_plans WHERE id = ?", [plan_id])


# ============================================================
# AI weekly plan generator
# ============================================================


class GenerateMealPlanRequest(BaseModel):
    prompt: str
    start_date: str  # ISO YYYY-MM-DD
    days: int = 7
    servings: int = 4
    slots: list[str] = ["dinner"]  # which slots to fill


class _PlannedMeal(BaseModel):
    day_offset: int  # 0..days-1
    slot: str        # "breakfast" | "lunch" | "dinner"
    use_recipe_id: str | None = None  # if matches an existing saved recipe
    new_recipe_prompt: str | None = None  # otherwise generate one with this prompt
    portions: float = 1


class _PlannedWeek(BaseModel):
    plan_name: str
    meals: list[_PlannedMeal]


_PLAN_MODEL = os.getenv("OPENAI_RECIPE_MODEL", "openai:gpt-4o")


def _list_existing_recipes_for_planner(household_id: str) -> str:
    with get_recipe_db() as conn:
        rows = conn.execute(
            "SELECT id, name, servings FROM recipes WHERE household_id = ? "
            "ORDER BY updated_at DESC LIMIT 200",
            [household_id],
        ).fetchall()
    if not rows:
        return "(no saved recipes — every meal must be generated fresh)"
    return "\n".join(f"id={r['id']} | {r['name']} (serves {r['servings']})" for r in rows)


@router.post("/generate", response_model=MealPlanOut)
async def generate_meal_plan(
    body: GenerateMealPlanRequest,
    household_id: str = DEFAULT_HOUSEHOLD_ID,
):
    """LLM-powered weekly plan generator.

    Two-stage:
    1. Planner agent decides what to cook each day, choosing existing recipes
       when reasonable and proposing prompts for new ones when needed.
    2. For every "new recipe" slot, we call the existing recipe generator
       (concurrently is overkill — sequential keeps log readable and respects
       OpenAI rate limits).
    Then assemble a meal plan and persist it."""
    from api.recipe_gen import generate_recipe

    if body.days < 1 or body.days > 14:
        raise HTTPException(400, "days must be 1..14")
    if not body.slots:
        raise HTTPException(400, "slots must not be empty")

    existing_recipes_listing = _list_existing_recipes_for_planner(household_id)

    planner_system_prompt = (
        "You are a weekly meal planner. Given a user brief and the household's "
        "existing saved recipes, design a coherent meal plan for the requested "
        "days and slots.\n\n"
        "Rules:\n"
        "- For each slot you fill, EITHER set use_recipe_id to one of the listed "
        "  saved recipes (use the exact id), OR set new_recipe_prompt to a short "
        "  description for a new recipe to be generated. Never both, never neither.\n"
        "- Reuse existing recipes when they fit the brief — don't generate "
        "  duplicates. Variety matters: avoid the same protein two days in a row.\n"
        "- Honour dietary constraints (vegetarian, gluten-free, etc.) the user "
        "  states in the brief.\n"
        "- new_recipe_prompt should be evocative and specific: 'Lemon-garlic cod "
        "  with crushed potatoes' beats 'fish dinner'.\n"
        "- day_offset is 0-indexed (0 = first day).\n"
        "- portions defaults to 1 = one portion-set for the household; usually "
        "  leave at 1 unless the user wants leftovers.\n"
        "- plan_name should be evocative: 'Spring Mediterranean Week', not 'Plan'.\n"
    )

    planner = Agent(_PLAN_MODEL, output_type=_PlannedWeek, system_prompt=planner_system_prompt)

    user_brief = (
        f"Brief: {body.prompt}\n\n"
        f"Days: {body.days}\n"
        f"Slots to fill each day: {', '.join(body.slots)}\n"
        f"Default portions per slot: {body.servings}\n\n"
        f"Existing saved recipes:\n{existing_recipes_listing}"
    )

    overall_start = time.monotonic()
    log.warning("[plan-gen] stage 1 planner starting (prompt=%r, days=%d)", body.prompt[:60], body.days)

    try:
        planner_start = time.monotonic()
        planned = (await planner.run(user_brief)).output
        log.warning(
            "[plan-gen] stage 1 planner done in %.1fs — %d meals proposed",
            time.monotonic() - planner_start, len(planned.meals),
        )
    except Exception as e:
        log.exception("[plan-gen] planner failed")
        raise HTTPException(500, f"Plan generation failed: {e}")

    # Validate existing recipe ids
    with get_recipe_db() as conn:
        valid_ids = {
            r["id"] for r in conn.execute(
                "SELECT id FROM recipes WHERE household_id = ?", [household_id],
            ).fetchall()
        }

    # Filter to meals we'll actually use, dedup identical prompts, keep order.
    valid_meals: list[_PlannedMeal] = []
    unique_prompts: list[str] = []  # preserves order
    seen_prompts: set[str] = set()
    for meal in planned.meals:
        if meal.day_offset < 0 or meal.day_offset >= body.days:
            continue
        if meal.slot not in body.slots:
            continue
        if not meal.use_recipe_id and not meal.new_recipe_prompt:
            continue
        valid_meals.append(meal)
        if meal.new_recipe_prompt and meal.new_recipe_prompt not in seen_prompts:
            seen_prompts.add(meal.new_recipe_prompt)
            unique_prompts.append(meal.new_recipe_prompt)

    # Stage 2: generate all needed recipes concurrently (bounded by semaphore).
    # OpenAI gpt-4o TPM limit on this tier is 30k/min; each recipe uses 2-4k tokens.
    # Semaphore of 3 keeps us under the TPM ceiling while still cutting total time ~3x.
    concurrency = int(os.getenv("RECIPE_GEN_CONCURRENCY", "3"))
    sem = asyncio.Semaphore(concurrency)

    async def gen_one(prompt: str) -> tuple[str, object | None]:
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
        stage2_start = time.monotonic()
        results = await asyncio.gather(*(gen_one(p) for p in unique_prompts))
        log.warning(
            "[plan-gen] stage 2 done in %.1fs (%d succeeded, %d failed)",
            time.monotonic() - stage2_start,
            sum(1 for _, g in results if g is not None),
            sum(1 for _, g in results if g is None),
        )
    else:
        results = []

    # Persist the new recipes and build prompt → recipe_id map.
    prompt_to_recipe_id: dict[str, str] = {}
    plan_id = new_id()
    with get_recipe_db() as conn:
        conn.execute(
            "INSERT INTO meal_plans (id, household_id, name, start_date) VALUES (?, ?, ?, ?)",
            [plan_id, household_id, planned.plan_name, body.start_date],
        )
        for prompt, gen in results:
            if gen is None:
                continue
            rid = new_id()
            conn.execute(
                "INSERT INTO recipes (id, household_id, name, instructions, servings) "
                "VALUES (?, ?, ?, ?, ?)",
                [rid, household_id, gen.name, json.dumps(gen.instructions), body.servings],
            )
            for ing in gen.ingredients:
                conn.execute(
                    "INSERT INTO recipe_ingredients (id, recipe_id, fdc_id, quantity_g) "
                    "VALUES (?, ?, ?, ?)",
                    [new_id(), rid, ing.fdc_id, ing.quantity_g],
                )
            prompt_to_recipe_id[prompt] = rid

        # Assemble the plan entries.
        for meal in valid_meals:
            recipe_id: str | None = None
            if meal.use_recipe_id and meal.use_recipe_id in valid_ids:
                recipe_id = meal.use_recipe_id
            elif meal.new_recipe_prompt:
                recipe_id = prompt_to_recipe_id.get(meal.new_recipe_prompt)

            if not recipe_id:
                continue

            plan_date = (
                datetime.fromisoformat(body.start_date) + timedelta(days=meal.day_offset)
            ).strftime("%Y-%m-%d")

            conn.execute(
                "INSERT INTO meal_plan_entries (id, meal_plan_id, recipe_id, plan_date, slot, portions) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [new_id(), plan_id, recipe_id, plan_date, meal.slot, max(1.0, float(meal.portions))],
            )

        out = _build_plan_out(conn, plan_id)

    log.warning(
        "[plan-gen] DONE in %.1fs total — plan '%s' with %d entries",
        time.monotonic() - overall_start, out.name, len(out.entries),
    )
    return out


@router.post("/{plan_id}/shopping-list", response_model=ShoppingListOut)
def shopping_list_from_plan(plan_id: str, household_id: str = DEFAULT_HOUSEHOLD_ID):
    """Consolidate all entries in a plan into a single shopping list.

    Entries for the same recipe on different days are summed, so an ingredient
    used across three dinners shows up as one line."""
    with get_recipe_db() as conn:
        plan = conn.execute(
            "SELECT id FROM meal_plans WHERE id = ? AND household_id = ?",
            [plan_id, household_id],
        ).fetchone()
        if not plan:
            raise HTTPException(404, "Meal plan not found")

        entries = conn.execute(
            "SELECT recipe_id, portions FROM meal_plan_entries WHERE meal_plan_id = ?",
            [plan_id],
        ).fetchall()

    # Sum portions per recipe — the shopping generator already consolidates ingredients.
    totals: dict[str, float] = {}
    for e in entries:
        totals[e["recipe_id"]] = totals.get(e["recipe_id"], 0) + float(e["portions"])

    selections = [
        ShoppingRecipeSelection(recipe_id=rid, portions=pts)
        for rid, pts in totals.items()
    ]
    return generate_shopping_list(selections, household_id=household_id)
