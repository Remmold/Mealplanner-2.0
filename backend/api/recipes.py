"""Recipe CRUD endpoints."""

from fastapi import APIRouter, HTTPException

from api.database import get_connection as get_duckdb
from api.models import RecipeCreate, RecipeIngredientOut, RecipeOut, RecipeUpdate
from api.recipe_db import DEFAULT_HOUSEHOLD_ID, get_recipe_db, new_id

router = APIRouter(prefix="/recipes", tags=["recipes"])


def _load_ingredient_names(fdc_ids: list[int]) -> dict[int, str]:
    """Look up simple_name from DuckDB common_ingredients."""
    if not fdc_ids:
        return {}
    placeholders = ", ".join(["?"] * len(fdc_ids))
    with get_duckdb() as conn:
        rows = conn.execute(
            f"SELECT fdc_id, simple_name FROM main.common_ingredients WHERE fdc_id IN ({placeholders})",
            fdc_ids,
        ).fetchall()
    return {row[0]: row[1] for row in rows}


def _build_recipe_out(conn, recipe_id: str) -> RecipeOut:
    row = conn.execute("SELECT * FROM recipes WHERE id = ?", [recipe_id]).fetchone()
    if not row:
        raise HTTPException(404, "Recipe not found")

    db_ingredients = conn.execute(
        "SELECT fdc_id, quantity_g FROM recipe_ingredients WHERE recipe_id = ? ORDER BY rowid",
        [recipe_id],
    ).fetchall()

    fdc_ids = [ing["fdc_id"] for ing in db_ingredients]
    names = _load_ingredient_names(fdc_ids)

    return RecipeOut(
        id=row["id"],
        household_id=row["household_id"],
        name=row["name"],
        ingredients=[
            RecipeIngredientOut(
                fdc_id=ing["fdc_id"],
                quantity_g=ing["quantity_g"],
                ingredient_name=names.get(ing["fdc_id"]),
            )
            for ing in db_ingredients
        ],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("", response_model=list[RecipeOut])
def list_recipes(household_id: str = DEFAULT_HOUSEHOLD_ID):
    with get_recipe_db() as conn:
        rows = conn.execute(
            "SELECT id FROM recipes WHERE household_id = ? ORDER BY updated_at DESC",
            [household_id],
        ).fetchall()
        return [_build_recipe_out(conn, row["id"]) for row in rows]


@router.post("", response_model=RecipeOut, status_code=201)
def create_recipe(body: RecipeCreate, household_id: str = DEFAULT_HOUSEHOLD_ID):
    recipe_id = new_id()

    with get_recipe_db() as conn:
        conn.execute(
            "INSERT INTO recipes (id, household_id, name) VALUES (?, ?, ?)",
            [recipe_id, household_id, body.name],
        )
        for ing in body.ingredients:
            conn.execute(
                "INSERT INTO recipe_ingredients (id, recipe_id, fdc_id, quantity_g) VALUES (?, ?, ?, ?)",
                [new_id(), recipe_id, ing.fdc_id, ing.quantity_g],
            )
        return _build_recipe_out(conn, recipe_id)


@router.get("/{recipe_id}", response_model=RecipeOut)
def get_recipe(recipe_id: str):
    with get_recipe_db() as conn:
        return _build_recipe_out(conn, recipe_id)


@router.put("/{recipe_id}", response_model=RecipeOut)
def update_recipe(recipe_id: str, body: RecipeUpdate):
    with get_recipe_db() as conn:
        existing = conn.execute("SELECT id FROM recipes WHERE id = ?", [recipe_id]).fetchone()
        if not existing:
            raise HTTPException(404, "Recipe not found")

        if body.name is not None:
            conn.execute(
                "UPDATE recipes SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                [body.name, recipe_id],
            )

        if body.ingredients is not None:
            conn.execute("DELETE FROM recipe_ingredients WHERE recipe_id = ?", [recipe_id])
            for ing in body.ingredients:
                conn.execute(
                    "INSERT INTO recipe_ingredients (id, recipe_id, fdc_id, quantity_g) "
                    "VALUES (?, ?, ?, ?)",
                    [new_id(), recipe_id, ing.fdc_id, ing.quantity_g],
                )
            conn.execute(
                "UPDATE recipes SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                [recipe_id],
            )

        return _build_recipe_out(conn, recipe_id)


@router.delete("/{recipe_id}", status_code=204)
def delete_recipe(recipe_id: str):
    with get_recipe_db() as conn:
        existing = conn.execute("SELECT id FROM recipes WHERE id = ?", [recipe_id]).fetchone()
        if not existing:
            raise HTTPException(404, "Recipe not found")
        conn.execute("DELETE FROM recipes WHERE id = ?", [recipe_id])
