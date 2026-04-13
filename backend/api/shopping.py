"""Shopping list generation: scale recipes by portions, consolidate, unit-convert, order by store layout."""

import math
from collections import defaultdict

from fastapi import APIRouter, HTTPException

from api.database import get_connection as get_duckdb
from api.models import (
    ShoppingListCategory,
    ShoppingListItem,
    ShoppingListOut,
    ShoppingRecipeSelection,
)
from api.recipe_db import DEFAULT_HOUSEHOLD_ID, get_recipe_db

router = APIRouter(prefix="/shopping-lists", tags=["shopping"])


def _round_up(value: float, step: float) -> float:
    if step <= 0:
        return value
    return math.ceil(value / step) * step


@router.post("/generate", response_model=ShoppingListOut)
def generate_shopping_list(
    selections: list[ShoppingRecipeSelection],
    household_id: str = DEFAULT_HOUSEHOLD_ID,
):
    if not selections:
        return ShoppingListOut(categories=[], missing_recipes=[])

    # 1. Load recipes + ingredients from SQLite, scale by portions/servings, sum by fdc_id
    totals_g: dict[int, float] = defaultdict(float)
    missing: list[str] = []

    with get_recipe_db() as conn:
        for sel in selections:
            recipe = conn.execute(
                "SELECT servings FROM recipes WHERE id = ? AND household_id = ?",
                [sel.recipe_id, household_id],
            ).fetchone()
            if not recipe:
                missing.append(sel.recipe_id)
                continue

            servings = max(int(recipe["servings"] or 4), 1)
            scale = sel.portions / servings

            ingredients = conn.execute(
                "SELECT fdc_id, quantity_g FROM recipe_ingredients WHERE recipe_id = ?",
                [sel.recipe_id],
            ).fetchall()
            for ing in ingredients:
                totals_g[ing["fdc_id"]] += ing["quantity_g"] * scale

        # 2. Load unit overrides + layout
        unit_rows = conn.execute(
            "SELECT fdc_id, display_unit, grams_per_unit, round_step FROM ingredient_units"
        ).fetchall()
        units = {r["fdc_id"]: r for r in unit_rows}

        layout_rows = conn.execute(
            "SELECT category, sort_index FROM store_layout WHERE household_id = ? ORDER BY sort_index",
            [household_id],
        ).fetchall()
        layout = {r["category"]: r["sort_index"] for r in layout_rows}

    if not totals_g:
        return ShoppingListOut(categories=[], missing_recipes=missing)

    # 3. Look up names + categories (curated union: dbt seed ∪ pantry)
    from api.ingredients import load_all_curated_meta, map_food_group
    curated = load_all_curated_meta()
    meta: dict[int, dict] = {}
    for fdc_id in totals_g:
        if fdc_id in curated:
            meta[fdc_id] = {"name": curated[fdc_id]["simple_name"], "category": curated[fdc_id]["category"]}

    # Fallback: any fdc_id not in curated (e.g. LLM used a USDA ingredient directly) — pull from USDA
    missing_ids = [fid for fid in totals_g if fid not in meta]
    if missing_ids:
        placeholders = ", ".join(["?"] * len(missing_ids))
        with get_duckdb() as conn:
            rows = conn.execute(
                f"SELECT fdc_id, name, food_group FROM usda.ingredients WHERE fdc_id IN ({placeholders})",
                missing_ids,
            ).fetchall()
        for r in rows:
            meta[r[0]] = {"name": r[1], "category": map_food_group(r[2])}

    # 4. Build items with unit conversion
    grouped: dict[str, list[ShoppingListItem]] = defaultdict(list)
    for fdc_id, grams in totals_g.items():
        info = meta.get(fdc_id)
        if not info:
            continue  # ingredient disappeared from curated list
        name = info["name"]
        category = info["category"] or "Other"

        unit = units.get(fdc_id)
        if unit:
            raw = grams / unit["grams_per_unit"]
            display_qty = _round_up(raw, unit["round_step"])
            display_unit = unit["display_unit"]
        else:
            display_qty = _round_up(grams, 10)  # round to nearest 10g up
            display_unit = "g"

        grouped[category].append(ShoppingListItem(
            fdc_id=fdc_id,
            name=name,
            category=category,
            quantity_g=round(grams, 1),
            display_quantity=display_qty,
            display_unit=display_unit,
        ))

    # 5. Order categories by store layout, then alphabetize items within each
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


@router.get("/store-layout", response_model=list[str])
def get_store_layout(household_id: str = DEFAULT_HOUSEHOLD_ID):
    """Return category names in current store order."""
    with get_recipe_db() as conn:
        rows = conn.execute(
            "SELECT category FROM store_layout WHERE household_id = ? ORDER BY sort_index",
            [household_id],
        ).fetchall()
    return [r["category"] for r in rows]


@router.put("/store-layout", response_model=list[str])
def update_store_layout(
    categories: list[str],
    household_id: str = DEFAULT_HOUSEHOLD_ID,
):
    """Replace the household's store layout with the given ordered list."""
    if not categories:
        raise HTTPException(400, "At least one category required")
    with get_recipe_db() as conn:
        conn.execute("DELETE FROM store_layout WHERE household_id = ?", [household_id])
        conn.executemany(
            "INSERT INTO store_layout (household_id, category, sort_index) VALUES (?, ?, ?)",
            [(household_id, cat, i) for i, cat in enumerate(categories)],
        )
    return categories
