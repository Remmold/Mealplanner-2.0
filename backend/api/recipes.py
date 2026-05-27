"""Recipe CRUD endpoints (Postgres-backed; RLS-scoped per household)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

import asyncpg

from api.auth import CurrentUser, get_current_user
from api.db import get_current_household_id, user_tx
from api.models import (
    GenerateRecipeRequest,
    GeneratedRecipeOut,
    RecipeCreate,
    RecipeIngredientOut,
    RecipeOut,
    RecipeUpdate,
)

router = APIRouter(prefix="/recipes", tags=["recipes"])


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


async def _usda_names_for(
    conn: asyncpg.Connection, fdc_ids: list[int]
) -> dict[int, str]:
    if not fdc_ids:
        return {}
    rows = await conn.fetch(
        "SELECT fdc_id, description FROM hearth.usda_ingredients "
        "WHERE fdc_id = ANY($1::int[])",
        list({int(f) for f in fdc_ids}),
    )
    return {r["fdc_id"]: r["description"] for r in rows}


async def _load_ingredient_names(
    conn: asyncpg.Connection, fdc_ids: list[int]
) -> dict[int, str]:
    """Map fdc_id -> simple_name. Curated pantry wins; USDA description falls back.
    Aliases dereferenced via the in-memory catalog cache."""
    if not fdc_ids:
        return {}
    from api.ingredients import load_all_curated_meta, resolve_fdc_id

    meta = load_all_curated_meta()
    result: dict[int, str] = {}
    canonicals: dict[int, int] = {}
    for fid in fdc_ids:
        canonical = resolve_fdc_id(fid)
        canonicals[fid] = canonical
        if canonical in meta:
            result[fid] = meta[canonical]["simple_name"]

    missing = [fid for fid in fdc_ids if fid not in result]
    if missing:
        usda = await _usda_names_for(conn, [canonicals[m] for m in missing])
        for fid in missing:
            name = usda.get(canonicals[fid])
            if name:
                result[fid] = name
    return result


async def _build_recipe_out(
    conn: asyncpg.Connection, recipe_id: str
) -> RecipeOut:
    row = await conn.fetchrow(
        "SELECT id, household_id, name, instructions, servings, "
        "image_path, created_at, updated_at "
        "FROM hearth.recipes WHERE id = $1::uuid",
        recipe_id,
    )
    if row is None:
        raise HTTPException(404, "Recipe not found")

    ing_rows = await conn.fetch(
        "SELECT fdc_id, quantity_g FROM hearth.recipe_ingredients "
        "WHERE recipe_id = $1::uuid ORDER BY id",
        recipe_id,
    )

    fdc_ids = [r["fdc_id"] for r in ing_rows]
    names = await _load_ingredient_names(conn, fdc_ids)

    # instructions is jsonb; the codec returns a Python list directly.
    instructions = row["instructions"] if isinstance(row["instructions"], list) else []

    return RecipeOut(
        id=str(row["id"]),
        household_id=str(row["household_id"]),
        name=row["name"],
        ingredients=[
            RecipeIngredientOut(
                fdc_id=r["fdc_id"],
                quantity_g=float(r["quantity_g"]),
                ingredient_name=names.get(r["fdc_id"]),
            )
            for r in ing_rows
        ],
        instructions=instructions,
        servings=row["servings"],
        image_path=row["image_path"],
        created_at=row["created_at"].isoformat() if row["created_at"] else "",
        updated_at=row["updated_at"].isoformat() if row["updated_at"] else "",
    )


async def _ensure_recipe_visible(
    conn: asyncpg.Connection, recipe_id: str
) -> None:
    """RLS already hides cross-household recipes, but a SELECT returning zero
    rows looks the same as 'recipe not found' — give the caller a clean 404."""
    exists = await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM hearth.recipes WHERE id = $1::uuid)",
        recipe_id,
    )
    if not exists:
        raise HTTPException(404, "Recipe not found")


# ----------------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------------


@router.get("", response_model=list[RecipeOut])
async def list_recipes(user: CurrentUser = Depends(get_current_user)):
    async with user_tx(user) as conn:
        rows = await conn.fetch(
            "SELECT id::text AS id FROM hearth.recipes ORDER BY updated_at DESC"
        )
        return [await _build_recipe_out(conn, r["id"]) for r in rows]


@router.post("", response_model=RecipeOut, status_code=201)
async def create_recipe(
    body: RecipeCreate,
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    async with user_tx(user) as conn:
        new_row = await conn.fetchrow(
            """
            INSERT INTO hearth.recipes (household_id, name, instructions, servings)
            VALUES ($1::uuid, $2, $3::jsonb, $4)
            RETURNING id::text AS id
            """,
            household_id, body.name, body.instructions, body.servings,
        )
        recipe_id = new_row["id"]

        for ing in body.ingredients:
            await conn.execute(
                "INSERT INTO hearth.recipe_ingredients (recipe_id, fdc_id, quantity_g) "
                "VALUES ($1::uuid, $2, $3)",
                recipe_id, ing.fdc_id, ing.quantity_g,
            )
        return await _build_recipe_out(conn, recipe_id)


@router.post("/generate", response_model=GeneratedRecipeOut)
async def generate_recipe_endpoint(
    body: GenerateRecipeRequest,
    household_id: str = Depends(get_current_household_id),
):
    from api.credits import debit, require_credits
    from api.recipe_gen import generate_recipe

    await require_credits(household_id, "recipe_gen")

    try:
        result = await generate_recipe(body.prompt)
    except Exception as e:
        raise HTTPException(500, f"Recipe generation failed: {e}")

    await debit(household_id, "recipe_gen")

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
    user: CurrentUser = Depends(get_current_user),
):
    async with user_tx(user) as conn:
        await _ensure_recipe_visible(conn, recipe_id)
        return await _build_recipe_out(conn, recipe_id)


@router.put("/{recipe_id}", response_model=RecipeOut)
async def update_recipe(
    recipe_id: str,
    body: RecipeUpdate,
    user: CurrentUser = Depends(get_current_user),
):
    async with user_tx(user) as conn:
        await _ensure_recipe_visible(conn, recipe_id)

        if body.name is not None:
            await conn.execute(
                "UPDATE hearth.recipes SET name = $1, updated_at = now() "
                "WHERE id = $2::uuid",
                body.name, recipe_id,
            )

        if body.instructions is not None:
            await conn.execute(
                "UPDATE hearth.recipes SET instructions = $1::jsonb, updated_at = now() "
                "WHERE id = $2::uuid",
                body.instructions, recipe_id,
            )

        if body.servings is not None:
            await conn.execute(
                "UPDATE hearth.recipes SET servings = $1, updated_at = now() "
                "WHERE id = $2::uuid",
                body.servings, recipe_id,
            )

        if body.ingredients is not None:
            await conn.execute(
                "DELETE FROM hearth.recipe_ingredients WHERE recipe_id = $1::uuid",
                recipe_id,
            )
            for ing in body.ingredients:
                await conn.execute(
                    "INSERT INTO hearth.recipe_ingredients (recipe_id, fdc_id, quantity_g) "
                    "VALUES ($1::uuid, $2, $3)",
                    recipe_id, ing.fdc_id, ing.quantity_g,
                )
            await conn.execute(
                "UPDATE hearth.recipes SET updated_at = now() WHERE id = $1::uuid",
                recipe_id,
            )

        return await _build_recipe_out(conn, recipe_id)


@router.delete("/{recipe_id}", status_code=204)
async def delete_recipe(
    recipe_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    async with user_tx(user) as conn:
        await _ensure_recipe_visible(conn, recipe_id)
        await conn.execute(
            "DELETE FROM hearth.recipes WHERE id = $1::uuid",
            recipe_id,
        )
