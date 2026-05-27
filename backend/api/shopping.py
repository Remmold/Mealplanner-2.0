"""Shopping list generation: scale recipes by portions, consolidate,
unit-convert, order by store layout. Postgres-backed."""

from __future__ import annotations

import math
from collections import defaultdict

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from api.auth import CurrentUser, get_current_user
from api.db import get_current_household_id, user_tx
from api.models import (
    ShoppingListCategory,
    ShoppingListItem,
    ShoppingListOut,
    ShoppingRecipeSelection,
    ShoppingTemplateItemIn,
    ShoppingTemplateItemOut,
)

router = APIRouter(prefix="/shopping-lists", tags=["shopping"])


def _round_up(value: float, step: float) -> float:
    if step <= 0:
        return value
    return math.ceil(value / step) * step


async def _usda_meta_for(
    conn: asyncpg.Connection, fdc_ids: list[int]
) -> dict[int, dict]:
    """Map fdc_id -> {name, category} from USDA, with food_group mapped to
    our display category. Used as a fallback for ids outside the curated catalog."""
    if not fdc_ids:
        return {}
    from api.ingredients import map_food_group
    rows = await conn.fetch(
        "SELECT fdc_id, description, food_group FROM hearth.usda_ingredients "
        "WHERE fdc_id = ANY($1::int[])",
        list({int(f) for f in fdc_ids}),
    )
    return {
        r["fdc_id"]: {"name": r["description"], "category": map_food_group(r["food_group"])}
        for r in rows
    }


@router.post("/generate", response_model=ShoppingListOut)
async def generate_shopping_list(
    selections: list[ShoppingRecipeSelection],
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
    include_template: bool = True,
):
    from api.ingredients import load_all_curated_meta, resolve_fdc_id
    from api import catalog_cache

    aliases = catalog_cache.get_aliases()
    curated = load_all_curated_meta()
    units = catalog_cache.get_units()

    totals_g: dict[int, float] = defaultdict(float)
    sources: dict[int, set[str]] = defaultdict(set)
    notes: dict[int, str] = {}
    missing: list[str] = []

    async with user_tx(user) as conn:
        # Recipes + their ingredients, scaled by requested portions.
        for sel in selections:
            recipe = await conn.fetchrow(
                "SELECT servings FROM hearth.recipes WHERE id = $1::uuid",
                sel.recipe_id,
            )
            if recipe is None:
                missing.append(sel.recipe_id)
                continue

            servings = max(int(recipe["servings"] or 4), 1)
            scale = sel.portions / servings

            ing_rows = await conn.fetch(
                "SELECT fdc_id, quantity_g FROM hearth.recipe_ingredients "
                "WHERE recipe_id = $1::uuid",
                sel.recipe_id,
            )
            for ing in ing_rows:
                canonical = resolve_fdc_id(ing["fdc_id"])
                totals_g[canonical] += float(ing["quantity_g"]) * scale
                sources[canonical].add("recipe")

        # Household "always buy" template, if requested.
        if include_template:
            tmpl_rows = await conn.fetch(
                "SELECT fdc_id, quantity_g, note FROM hearth.shopping_list_template "
                "WHERE household_id = $1::uuid",
                household_id,
            )
            for row in tmpl_rows:
                canonical = resolve_fdc_id(row["fdc_id"])
                totals_g[canonical] += float(row["quantity_g"])
                sources[canonical].add("template")
                if row["note"]:
                    notes[canonical] = row["note"]

        # Store layout for category ordering.
        layout_rows = await conn.fetch(
            "SELECT category, sort_index FROM hearth.store_layout "
            "WHERE household_id = $1::uuid ORDER BY sort_index",
            household_id,
        )
        layout = {r["category"]: r["sort_index"] for r in layout_rows}

        if not totals_g:
            return ShoppingListOut(categories=[], missing_recipes=missing)

        # Resolve names + categories.
        meta: dict[int, dict] = {}
        for fdc_id in totals_g:
            if fdc_id in curated:
                meta[fdc_id] = {
                    "name": curated[fdc_id]["simple_name"],
                    "category": curated[fdc_id]["category"],
                }
        # USDA fallback for anything not in curated.
        missing_ids = [fid for fid in totals_g if fid not in meta]
        if missing_ids:
            meta.update(await _usda_meta_for(conn, missing_ids))

    # Build items with unit conversion.
    grouped: dict[str, list[ShoppingListItem]] = defaultdict(list)
    for fdc_id, grams in totals_g.items():
        info = meta.get(fdc_id)
        if not info:
            continue
        name = info["name"]
        category = info["category"] or "Other"

        unit = units.get(fdc_id)
        if unit:
            raw = grams / unit["grams_per_unit"]
            display_qty = _round_up(raw, unit["round_step"])
            display_unit = unit["display_unit"]
        else:
            display_qty = _round_up(grams, 10)
            display_unit = "g"

        item_sources = sources.get(fdc_id, {"recipe"})
        if item_sources == {"template"}:
            source_label = "template"
        elif item_sources == {"recipe"}:
            source_label = "recipe"
        else:
            source_label = "both"

        grouped[category].append(ShoppingListItem(
            fdc_id=fdc_id,
            name=name,
            category=category,
            quantity_g=round(grams, 1),
            display_quantity=display_qty,
            display_unit=display_unit,
            source=source_label,
            note=notes.get(fdc_id),
        ))

    DEFAULT_SORT = 9999
    categories = []
    for category, items in grouped.items():
        items.sort(key=lambda it: it.name.lower())
        categories.append(ShoppingListCategory(
            category=category,
            sort_index=layout.get(category, DEFAULT_SORT),
            items=items,
        ))
    categories.sort(key=lambda c: (c.sort_index, c.category))

    return ShoppingListOut(categories=categories, missing_recipes=missing)


# ----------------------------------------------------------------------------
# Store layout (per-household category ordering)
# ----------------------------------------------------------------------------


@router.get("/store-layout", response_model=list[str])
async def get_store_layout(
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    async with user_tx(user) as conn:
        rows = await conn.fetch(
            "SELECT category FROM hearth.store_layout "
            "WHERE household_id = $1::uuid ORDER BY sort_index",
            household_id,
        )
    return [r["category"] for r in rows]


@router.put("/store-layout", response_model=list[str])
async def update_store_layout(
    categories: list[str],
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    if not categories:
        raise HTTPException(400, "At least one category required")
    async with user_tx(user) as conn:
        await conn.execute(
            "DELETE FROM hearth.store_layout WHERE household_id = $1::uuid",
            household_id,
        )
        for i, cat in enumerate(categories):
            await conn.execute(
                "INSERT INTO hearth.store_layout (household_id, category, sort_index) "
                "VALUES ($1::uuid, $2, $3)",
                household_id, cat, i,
            )
    return categories


# ----------------------------------------------------------------------------
# Shopping list template
# ----------------------------------------------------------------------------


async def _template_item_out(
    conn: asyncpg.Connection,
    fdc_id: int,
    quantity_g: float,
    note: str | None,
) -> ShoppingTemplateItemOut:
    from api.ingredients import load_all_curated_meta
    from api import catalog_cache

    curated = load_all_curated_meta()
    info = curated.get(fdc_id)
    if info:
        name = info["simple_name"]
        category = info["category"] or "Other"
    else:
        usda = await _usda_meta_for(conn, [fdc_id])
        if fdc_id not in usda:
            raise HTTPException(404, f"Ingredient {fdc_id} not found")
        name = usda[fdc_id]["name"]
        category = usda[fdc_id]["category"]

    units = catalog_cache.get_units()
    unit = units.get(fdc_id)
    if unit:
        display_qty = _round_up(quantity_g / unit["grams_per_unit"], unit["round_step"])
        display_unit = unit["display_unit"]
    else:
        display_qty = _round_up(quantity_g, 10)
        display_unit = "g"

    return ShoppingTemplateItemOut(
        fdc_id=fdc_id,
        name=name,
        category=category,
        quantity_g=round(quantity_g, 1),
        display_quantity=display_qty,
        display_unit=display_unit,
        note=note,
    )


@router.get("/template", response_model=list[ShoppingTemplateItemOut])
async def list_template(
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    async with user_tx(user) as conn:
        rows = await conn.fetch(
            "SELECT fdc_id, quantity_g, note FROM hearth.shopping_list_template "
            "WHERE household_id = $1::uuid",
            household_id,
        )
        items = [
            await _template_item_out(conn, r["fdc_id"], float(r["quantity_g"]), r["note"])
            for r in rows
        ]
    items.sort(key=lambda it: (it.category.lower(), it.name.lower()))
    return items


@router.post("/template", response_model=ShoppingTemplateItemOut, status_code=201)
async def upsert_template_item(
    body: ShoppingTemplateItemIn,
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    if body.quantity_g <= 0:
        raise HTTPException(400, "quantity_g must be positive")
    async with user_tx(user) as conn:
        await conn.execute(
            """
            INSERT INTO hearth.shopping_list_template
                (household_id, fdc_id, quantity_g, note)
            VALUES ($1::uuid, $2, $3, $4)
            ON CONFLICT (household_id, fdc_id) DO UPDATE SET
                quantity_g = excluded.quantity_g,
                note = excluded.note,
                updated_at = now()
            """,
            household_id, body.fdc_id, body.quantity_g, body.note,
        )
        return await _template_item_out(conn, body.fdc_id, body.quantity_g, body.note)


@router.put("/template/{fdc_id}", response_model=ShoppingTemplateItemOut)
async def update_template_item(
    fdc_id: int,
    body: ShoppingTemplateItemIn,
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    if body.fdc_id != fdc_id:
        raise HTTPException(400, "fdc_id in path and body must match")
    if body.quantity_g <= 0:
        raise HTTPException(400, "quantity_g must be positive")
    async with user_tx(user) as conn:
        result = await conn.execute(
            "UPDATE hearth.shopping_list_template SET quantity_g = $1, note = $2, "
            "updated_at = now() WHERE household_id = $3::uuid AND fdc_id = $4",
            body.quantity_g, body.note, household_id, fdc_id,
        )
        # asyncpg execute returns "UPDATE n"
        if result.endswith(" 0"):
            raise HTTPException(404, f"Template item {fdc_id} not found")
        return await _template_item_out(conn, fdc_id, body.quantity_g, body.note)


@router.delete("/template/{fdc_id}", status_code=204)
async def delete_template_item(
    fdc_id: int,
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    async with user_tx(user) as conn:
        await conn.execute(
            "DELETE FROM hearth.shopping_list_template "
            "WHERE household_id = $1::uuid AND fdc_id = $2",
            household_id, fdc_id,
        )


@router.get("/ingredient-units")
async def list_ingredient_units():
    """All display-unit overrides keyed by fdc_id (served from in-memory cache)."""
    from api import catalog_cache
    return {
        fdc_id: {
            "display_unit": u["display_unit"],
            "grams_per_unit": u["grams_per_unit"],
            "round_step": u["round_step"],
        }
        for fdc_id, u in catalog_cache.get_units().items()
    }
