"""Recipe CRUD endpoints (Postgres-backed; RLS-scoped per household)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

import asyncpg

from api.auth import CurrentUser, get_current_user
from api.db import get_current_household_id, user_tx
from api.recipe_translate import ensure_recipe_translation, localized
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
    """Map fdc_id -> kitchen-friendly display name. Curated pantry wins; if
    we fall back to USDA we clean the description first so the user sees
    'Tomatoes' instead of 'Tomatoes, red, ripe, raw'."""
    if not fdc_ids:
        return {}
    from api.ingredients import clean_usda_name, load_all_curated_meta, resolve_fdc_id

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
            raw = usda.get(canonicals[fid])
            if raw:
                result[fid] = clean_usda_name(raw)
    return result


async def _build_recipe_out(
    conn: asyncpg.Connection, recipe_id: str, locale: str = "en"
) -> RecipeOut:
    row = await conn.fetchrow(
        "SELECT id, household_id, name, instructions, translations, servings, meal_type, "
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
    base_instructions = row["instructions"] if isinstance(row["instructions"], list) else []
    name, instructions = localized(row["name"], base_instructions, row["translations"], locale)

    return RecipeOut(
        id=str(row["id"]),
        household_id=str(row["household_id"]),
        name=name,
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
        meal_type=row["meal_type"],
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
async def list_recipes(
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
    locale: str = Query("en"),
):
    """Batched fetch: one SELECT per table instead of the per-recipe walk
    that _build_recipe_out does for a single recipe. Cuts ~4N queries down
    to a constant ~5."""
    async with user_tx(user) as conn:
        recipe_rows = await conn.fetch(
            "SELECT id::text AS id, household_id, name, instructions, translations, servings, "
            "meal_type, image_path, created_at, updated_at "
            "FROM hearth.recipes ORDER BY updated_at DESC"
        )
        if not recipe_rows:
            return []

        recipe_ids = [r["id"] for r in recipe_rows]

        ing_rows = await conn.fetch(
            "SELECT recipe_id::text AS recipe_id, fdc_id, quantity_g, id "
            "FROM hearth.recipe_ingredients "
            "WHERE recipe_id = ANY($1::uuid[]) ORDER BY recipe_id, id",
            recipe_ids,
        )

        # Group ingredients per recipe and collect the global fdc_id set so
        # we can resolve names in one shot.
        ings_by_recipe: dict[str, list] = {}
        all_fdc_ids: set[int] = set()
        for ir in ing_rows:
            ings_by_recipe.setdefault(ir["recipe_id"], []).append(ir)
            all_fdc_ids.add(int(ir["fdc_id"]))

        names = await _load_ingredient_names(conn, list(all_fdc_ids))

    out: list[RecipeOut] = []
    for r in recipe_rows:
        base_instr = r["instructions"] if isinstance(r["instructions"], list) else []
        name, instructions = localized(r["name"], base_instr, r["translations"], locale)
        ings = ings_by_recipe.get(r["id"], [])
        out.append(RecipeOut(
            id=r["id"],
            household_id=str(r["household_id"]),
            name=name,
            ingredients=[
                RecipeIngredientOut(
                    fdc_id=ing["fdc_id"],
                    quantity_g=float(ing["quantity_g"]),
                    ingredient_name=names.get(ing["fdc_id"]),
                )
                for ing in ings
            ],
            instructions=instructions,
            servings=r["servings"],
            meal_type=r["meal_type"],
            image_path=r["image_path"],
            created_at=r["created_at"].isoformat() if r["created_at"] else "",
            updated_at=r["updated_at"].isoformat() if r["updated_at"] else "",
        ))
    return out


@router.post("", response_model=RecipeOut, status_code=201)
async def create_recipe(
    body: RecipeCreate,
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    async with user_tx(user) as conn:
        new_row = await conn.fetchrow(
            """
            INSERT INTO hearth.recipes (household_id, name, instructions, servings, meal_type)
            VALUES ($1::uuid, $2, $3::jsonb, $4, $5)
            RETURNING id::text AS id
            """,
            household_id, body.name, body.instructions, body.servings, body.meal_type,
        )
        recipe_id = new_row["id"]

        for ing in body.ingredients:
            await conn.execute(
                "INSERT INTO hearth.recipe_ingredients (recipe_id, fdc_id, quantity_g) "
                "VALUES ($1::uuid, $2, $3)",
                recipe_id, ing.fdc_id, ing.quantity_g,
            )
        out = await _build_recipe_out(conn, recipe_id)
    # Fill both languages in the background so it reads right in either UI.
    ensure_recipe_translation(recipe_id, "en")
    ensure_recipe_translation(recipe_id, "sv")
    return out


@router.post("/generate", response_model=GeneratedRecipeOut)
async def generate_recipe_endpoint(
    body: GenerateRecipeRequest,
    household_id: str = Depends(get_current_household_id),
):
    from api.credits import debit, require_credits
    from api.profile import load_profile
    from api.recipe_gen import generate_recipe

    await require_credits(household_id, "recipe_gen")

    # Keep generated recipes free of the household's allergens/dislikes (handled
    # by meaning, so non-English terms like "lök" still block onion).
    profile = await load_profile(household_id)
    try:
        result = await generate_recipe(
            body.prompt, allergies=profile.allergies, dislikes=profile.dislikes
        )
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


@router.post("/from-images", response_model=GeneratedRecipeOut)
async def recipe_from_images_endpoint(
    files: list[UploadFile] = File(...),
    locale: str = Query("en"),
    household_id: str = Depends(get_current_household_id),
):
    """Extract a structured recipe from up to 4 photos (cookbook page, handwritten
    card, screenshot). Returns the same shape as /generate so the frontend reviews
    + saves it through the normal builder flow."""
    from api.credits import debit, require_credits
    from api.recipe_gen import generate_recipe_from_images

    images: list[bytes] = []
    for f in (files or [])[:4]:
        data = await f.read()
        if data:
            images.append(data)
    if not images:
        raise HTTPException(400, "Upload at least one photo of a recipe.")

    await require_credits(household_id, "recipe_gen")
    try:
        result = await generate_recipe_from_images(images, locale=locale)
    except Exception as e:
        raise HTTPException(500, f"Recipe extraction failed: {e}")
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
    locale: str = Query("en"),
):
    async with user_tx(user) as conn:
        await _ensure_recipe_visible(conn, recipe_id)
        out = await _build_recipe_out(conn, recipe_id, locale)
    # Lazily fill this locale for next time if the recipe didn't have it.
    ensure_recipe_translation(recipe_id, locale)
    return out


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

        if body.meal_type is not None:
            await conn.execute(
                "UPDATE hearth.recipes SET meal_type = $1, updated_at = now() "
                "WHERE id = $2::uuid",
                body.meal_type or None, recipe_id,
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

        # Editing the text invalidates the stored translations — clear them so
        # nothing stale shows; they refill from the new base below.
        content_changed = body.name is not None or body.instructions is not None
        if content_changed:
            await conn.execute(
                "UPDATE hearth.recipes SET translations = '{}'::jsonb WHERE id = $1::uuid",
                recipe_id,
            )

        out = await _build_recipe_out(conn, recipe_id)
    if content_changed:
        ensure_recipe_translation(recipe_id, "en")
        ensure_recipe_translation(recipe_id, "sv")
    return out


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
