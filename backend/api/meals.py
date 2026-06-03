"""Meals — the household's flat calendar of dated meals.

This is the canonical API for the calendar UX. There is no concept of a
"meal plan" here; meals are just dated entries scoped to a household. The
chat agent and the calendar grid both speak this language now.

Storage is still hearth.meal_plan_entries (rename is too disruptive). The
2026-05-28 migration added household_id directly and made meal_plan_id
nullable so new entries don't need a plan wrapper. Legacy wizard-generated
plans still write entries here; they appear on the calendar exactly the
same way.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth import CurrentUser, get_current_user
from api.db import get_current_household_id, user_tx

router = APIRouter(prefix="/meals", tags=["meals"])


# ----------------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------------


class MealOut(BaseModel):
    id: str
    recipe_id: str
    recipe_name: str | None = None
    plan_date: str         # ISO YYYY-MM-DD
    slot: str | None = None
    portions: float
    image_path: str | None = None
    # Lunch-bag leftovers: set on a bag entry to the cook it came from; on a cook
    # entry, lunch_bags is how many bags (leftover days) it produced. A normal
    # single meal has source_entry_id=None and lunch_bags=0.
    source_entry_id: str | None = None
    lunch_bags: int = 0


class MealCreate(BaseModel):
    recipe_id: str
    plan_date: date
    slot: str | None = None
    portions: float = 1


class MealUpdate(BaseModel):
    plan_date: date | None = None
    slot: str | None = None
    portions: float | None = None


# ----------------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------------


@router.get("", response_model=list[MealOut])
async def list_meals(
    start: date = Query(..., description="Inclusive start date (ISO)"),
    end:   date = Query(..., description="Inclusive end date (ISO)"),
    user: CurrentUser = Depends(get_current_user),
):
    """Return every meal on the calendar between start and end inclusive."""
    if end < start:
        raise HTTPException(400, "end must be on or after start")
    async with user_tx(user) as conn:
        rows = await conn.fetch(
            """
            SELECT e.id::text              AS id,
                   e.recipe_id::text       AS recipe_id,
                   r.name                  AS recipe_name,
                   e.plan_date,
                   e.slot,
                   e.portions,
                   r.image_path,
                   e.source_entry_id::text AS source_entry_id,
                   (SELECT count(*) FROM hearth.meal_plan_entries c
                     WHERE c.source_entry_id = e.id) AS lunch_bags
            FROM hearth.meal_plan_entries e
            LEFT JOIN hearth.recipes r ON r.id = e.recipe_id
            WHERE e.plan_date BETWEEN $1::date AND $2::date
            ORDER BY e.plan_date, e.slot
            """,
            start, end,
        )
    return [
        MealOut(
            id=r["id"],
            recipe_id=r["recipe_id"],
            recipe_name=r["recipe_name"],
            plan_date=r["plan_date"].isoformat() if r["plan_date"] else "",
            slot=r["slot"],
            portions=float(r["portions"]),
            image_path=r["image_path"],
            source_entry_id=r["source_entry_id"],
            lunch_bags=int(r["lunch_bags"] or 0),
        )
        for r in rows
    ]


@router.post("", response_model=MealOut, status_code=201)
async def create_meal(
    body: MealCreate,
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    async with user_tx(user) as conn:
        recipe = await conn.fetchrow(
            "SELECT id::text AS id, name, image_path FROM hearth.recipes "
            "WHERE id = $1::uuid",
            body.recipe_id,
        )
        if recipe is None:
            raise HTTPException(404, "Recipe not found")
        row = await conn.fetchrow(
            """
            INSERT INTO hearth.meal_plan_entries
                (household_id, recipe_id, plan_date, slot, portions)
            VALUES ($1::uuid, $2::uuid, $3::date, $4, $5)
            RETURNING id::text AS id
            """,
            household_id, body.recipe_id, body.plan_date,
            body.slot, max(0.25, float(body.portions)),
        )
    return MealOut(
        id=row["id"],
        recipe_id=recipe["id"],
        recipe_name=recipe["name"],
        plan_date=body.plan_date.isoformat(),
        slot=body.slot,
        portions=float(body.portions),
        image_path=recipe["image_path"],
    )


@router.patch("/{meal_id}", response_model=MealOut)
async def update_meal(
    meal_id: str,
    body: MealUpdate,
    user: CurrentUser = Depends(get_current_user),
):
    async with user_tx(user) as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM hearth.meal_plan_entries WHERE id = $1::uuid",
            meal_id,
        )
        if existing is None:
            raise HTTPException(404, "Meal not found")
        if body.plan_date is not None:
            await conn.execute(
                "UPDATE hearth.meal_plan_entries SET plan_date = $1::date WHERE id = $2::uuid",
                body.plan_date, meal_id,
            )
        if body.slot is not None:
            await conn.execute(
                "UPDATE hearth.meal_plan_entries SET slot = $1 WHERE id = $2::uuid",
                body.slot, meal_id,
            )
        if body.portions is not None:
            await conn.execute(
                "UPDATE hearth.meal_plan_entries SET portions = $1 WHERE id = $2::uuid",
                max(0.25, float(body.portions)), meal_id,
            )
        row = await conn.fetchrow(
            """
            SELECT e.id::text         AS id,
                   e.recipe_id::text  AS recipe_id,
                   r.name             AS recipe_name,
                   e.plan_date,
                   e.slot,
                   e.portions,
                   r.image_path
            FROM hearth.meal_plan_entries e
            LEFT JOIN hearth.recipes r ON r.id = e.recipe_id
            WHERE e.id = $1::uuid
            """,
            meal_id,
        )
    return MealOut(
        id=row["id"],
        recipe_id=row["recipe_id"],
        recipe_name=row["recipe_name"],
        plan_date=row["plan_date"].isoformat() if row["plan_date"] else "",
        slot=row["slot"],
        portions=float(row["portions"]),
        image_path=row["image_path"],
    )


@router.delete("/{meal_id}", status_code=204)
async def delete_meal(
    meal_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    async with user_tx(user) as conn:
        result = await conn.execute(
            "DELETE FROM hearth.meal_plan_entries WHERE id = $1::uuid",
            meal_id,
        )
    if result.endswith(" 0"):
        raise HTTPException(404, "Meal not found")


# ----------------------------------------------------------------------------
# Shopping list — by date range, not by plan
# ----------------------------------------------------------------------------


@router.post("/shopping-list")
async def shopping_list_for_range(
    start: date = Query(...),
    end:   date = Query(...),
    include_template: bool = Query(True),
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    """Aggregate meals between start..end into a single store-ordered list."""
    from api.models import ShoppingRecipeSelection
    from api.shopping import generate_shopping_list

    if end < start:
        raise HTTPException(400, "end must be on or after start")

    async with user_tx(user) as conn:
        rows = await conn.fetch(
            "SELECT recipe_id::text AS recipe_id, portions "
            "FROM hearth.meal_plan_entries "
            "WHERE plan_date BETWEEN $1::date AND $2::date",
            start, end,
        )

    if not rows:
        raise HTTPException(400, "No meals on the calendar in that range")

    totals: dict[str, float] = {}
    for r in rows:
        totals[r["recipe_id"]] = totals.get(r["recipe_id"], 0) + float(r["portions"])

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
