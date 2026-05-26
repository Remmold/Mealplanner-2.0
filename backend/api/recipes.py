"""Recipe CRUD endpoints (SQLite-backed for now, scoped to the authenticated household).

The user's household_id is resolved from their JWT via Depends(get_current_household_id),
not from a query parameter. SQLite stays the storage for v1; the Postgres
migration of recipe data is its own task.
"""

import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from api.db import get_current_household_id, get_pool
from api.models import (
    GenerateRecipeRequest,
    GeneratedRecipeOut,
    RecipeCreate,
    RecipeIngredientOut,
    RecipeOut,
    RecipeUpdate,
)
from api.recipe_db import get_recipe_db, new_id

router = APIRouter(prefix="/recipes", tags=["recipes"])


async def _usda_names_for(fdc_ids: list[int]) -> dict[int, str]:
    """Fetch USDA `description` for the given fdc_ids from Postgres."""
    if not fdc_ids:
        return {}
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT fdc_id, description FROM hearth.usda_ingredients WHERE fdc_id = ANY($1::int[])",
            list({int(f) for f in fdc_ids}),
        )
    return {r["fdc_id"]: r["description"] for r in rows}


async def _load_ingredient_names(fdc_ids: list[int]) -> dict[int, str]:
    """Look up simple_name from the curated pantry (Postgres cache),
    falling back to USDA description. Aliases are dereferenced via the
    cache so recipes that stored an alias fdc_id still display correctly.
    """
    if not fdc_ids:
        return {}
    from api.ingredients import load_all_curated_meta, resolve_fdc_id

    meta = load_all_curated_meta()

    result: dict[int, str] = {}
    for fid in fdc_ids:
        canonical = resolve_fdc_id(fid)
        if canonical in meta:
            result[fid] = meta[canonical]["simple_name"]

    missing = [fid for fid in fdc_ids if fid not in result]
    if missing:
        canonical_missing = [resolve_fdc_id(f) for f in missing]
        usda_names = await _usda_names_for(canonical_missing)
        for orig, canonical in zip(missing, canonical_missing):
            if canonical in usda_names:
                result[orig] = usda_names[canonical]
    return result


async def _build_recipe_out(conn: sqlite3.Connection, recipe_id: str) -> RecipeOut:
    row = conn.execute("SELECT * FROM recipes WHERE id = ?", [recipe_id]).fetchone()
    if not row:
        raise HTTPException(404, "Recipe not found")

    db_ingredients = conn.execute(
        "SELECT fdc_id, quantity_g FROM recipe_ingredients WHERE recipe_id = ? ORDER BY rowid",
        [recipe_id],
    ).fetchall()

    fdc_ids = [ing["fdc_id"] for ing in db_ingredients]
    names = await _load_ingredient_names(fdc_ids)

    try:
        instructions = json.loads(row["instructions"]) if row["instructions"] else []
    except (json.JSONDecodeError, TypeError):
        instructions = []

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
        instructions=instructions,
        servings=row["servings"] if "servings" in row.keys() else 4,
        image_path=row["image_path"] if "image_path" in row.keys() else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _enforce_recipe_in_household(
    conn: sqlite3.Connection, recipe_id: str, household_id: str
) -> None:
    row = conn.execute(
        "SELECT household_id FROM recipes WHERE id = ?", [recipe_id]
    ).fetchone()
    if not row:
        raise HTTPException(404, "Recipe not found")
    if row["household_id"] != household_id:
        raise HTTPException(403, "Recipe belongs to a different household")


@router.get("", response_model=list[RecipeOut])
async def list_recipes(household_id: str = Depends(get_current_household_id)):
    with get_recipe_db() as conn:
        rows = conn.execute(
            "SELECT id FROM recipes WHERE household_id = ? ORDER BY updated_at DESC",
            [household_id],
        ).fetchall()
        return [await _build_recipe_out(conn, row["id"]) for row in rows]


@router.post("", response_model=RecipeOut, status_code=201)
async def create_recipe(
    body: RecipeCreate,
    household_id: str = Depends(get_current_household_id),
):
    recipe_id = new_id()

    with get_recipe_db() as conn:
        conn.execute(
            "INSERT INTO recipes (id, household_id, name, instructions, servings) "
            "VALUES (?, ?, ?, ?, ?)",
            [recipe_id, household_id, body.name, json.dumps(body.instructions), body.servings],
        )
        for ing in body.ingredients:
            conn.execute(
                "INSERT INTO recipe_ingredients (id, recipe_id, fdc_id, quantity_g) VALUES (?, ?, ?, ?)",
                [new_id(), recipe_id, ing.fdc_id, ing.quantity_g],
            )
        return await _build_recipe_out(conn, recipe_id)


@router.post("/generate", response_model=GeneratedRecipeOut)
async def generate_recipe_endpoint(
    body: GenerateRecipeRequest,
    _household_id: str = Depends(get_current_household_id),
):
    from api.recipe_gen import generate_recipe

    try:
        result = await generate_recipe(body.prompt)
    except Exception as e:
        raise HTTPException(500, f"Recipe generation failed: {e}")

    return GeneratedRecipeOut(
        name=result.name,
        ingredients=[
            {"fdc_id": ing.fdc_id, "name": ing.name, "quantity_g": ing.quantity_g}
            for ing in result.ingredients
        ],
        instructions=result.instructions,
    )


@router.get("/{recipe_id}", response_model=RecipeOut)
async def get_recipe(
    recipe_id: str,
    household_id: str = Depends(get_current_household_id),
):
    with get_recipe_db() as conn:
        await _enforce_recipe_in_household(conn, recipe_id, household_id)
        return await _build_recipe_out(conn, recipe_id)


@router.put("/{recipe_id}", response_model=RecipeOut)
async def update_recipe(
    recipe_id: str,
    body: RecipeUpdate,
    household_id: str = Depends(get_current_household_id),
):
    with get_recipe_db() as conn:
        await _enforce_recipe_in_household(conn, recipe_id, household_id)

        if body.name is not None:
            conn.execute(
                "UPDATE recipes SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                [body.name, recipe_id],
            )

        if body.instructions is not None:
            conn.execute(
                "UPDATE recipes SET instructions = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                [json.dumps(body.instructions), recipe_id],
            )

        if body.servings is not None:
            conn.execute(
                "UPDATE recipes SET servings = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                [body.servings, recipe_id],
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

        return await _build_recipe_out(conn, recipe_id)


@router.delete("/{recipe_id}", status_code=204)
async def delete_recipe(
    recipe_id: str,
    household_id: str = Depends(get_current_household_id),
):
    with get_recipe_db() as conn:
        await _enforce_recipe_in_household(conn, recipe_id, household_id)
        conn.execute("DELETE FROM recipes WHERE id = ?", [recipe_id])
