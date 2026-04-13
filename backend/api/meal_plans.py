"""Meal plan CRUD + shopping list generation from a plan."""

from fastapi import APIRouter, HTTPException

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
