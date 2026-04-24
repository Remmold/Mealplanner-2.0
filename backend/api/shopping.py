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
    ShoppingTemplateItemIn,
    ShoppingTemplateItemOut,
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
    include_template: bool = True,
):
    # Load alias map up-front so ingredient ids collapse to their canonical form
    # *before* we sum. This is what merges "Butter" + "Butter, Unsalted" on the list.
    from api.ingredients import load_aliases, resolve_fdc_id
    aliases = load_aliases()

    # 1. Load recipes + ingredients from SQLite, scale by portions/servings, sum by fdc_id.
    #    Also merge the household template (baseline "we always buy") when include_template.
    totals_g: dict[int, float] = defaultdict(float)
    sources: dict[int, set[str]] = defaultdict(set)
    notes: dict[int, str] = {}
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
                canonical = resolve_fdc_id(ing["fdc_id"], aliases)
                totals_g[canonical] += ing["quantity_g"] * scale
                sources[canonical].add("recipe")

        if include_template:
            template_rows = conn.execute(
                "SELECT fdc_id, quantity_g, note FROM shopping_list_template "
                "WHERE household_id = ?",
                [household_id],
            ).fetchall()
            for row in template_rows:
                canonical = resolve_fdc_id(row["fdc_id"], aliases)
                totals_g[canonical] += row["quantity_g"]
                sources[canonical].add("template")
                if row["note"]:
                    notes[canonical] = row["note"]

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


# --- Shopping list template (baseline items the household always buys) ---


def _template_item_out(fdc_id: int, quantity_g: float, note: str | None) -> ShoppingTemplateItemOut:
    """Enrich a raw template row with curated name/category and unit-converted qty."""
    from api.ingredients import load_all_curated_meta

    curated = load_all_curated_meta()
    info = curated.get(fdc_id)
    if info:
        name = info["simple_name"]
        category = info["category"] or "Other"
    else:
        # Fallback to USDA for ids outside the curated union (uncommon).
        from api.ingredients import map_food_group
        with get_duckdb() as conn:
            row = conn.execute(
                "SELECT name, food_group FROM usda.ingredients WHERE fdc_id = ?",
                [fdc_id],
            ).fetchone()
        if not row:
            raise HTTPException(404, f"Ingredient {fdc_id} not found")
        name = row[0]
        category = map_food_group(row[1])

    with get_recipe_db() as conn:
        unit_row = conn.execute(
            "SELECT display_unit, grams_per_unit, round_step FROM ingredient_units WHERE fdc_id = ?",
            [fdc_id],
        ).fetchone()

    if unit_row:
        display_qty = _round_up(quantity_g / unit_row["grams_per_unit"], unit_row["round_step"])
        display_unit = unit_row["display_unit"]
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
def list_template(household_id: str = DEFAULT_HOUSEHOLD_ID):
    """Return the household's persistent baseline items, enriched for display."""
    with get_recipe_db() as conn:
        rows = conn.execute(
            "SELECT fdc_id, quantity_g, note FROM shopping_list_template WHERE household_id = ?",
            [household_id],
        ).fetchall()
    items = [_template_item_out(r["fdc_id"], r["quantity_g"], r["note"]) for r in rows]
    items.sort(key=lambda it: (it.category.lower(), it.name.lower()))
    return items


@router.post("/template", response_model=ShoppingTemplateItemOut, status_code=201)
def upsert_template_item(
    body: ShoppingTemplateItemIn,
    household_id: str = DEFAULT_HOUSEHOLD_ID,
):
    """Add or replace a baseline item. Keyed on fdc_id — re-posting overwrites qty/note."""
    if body.quantity_g <= 0:
        raise HTTPException(400, "quantity_g must be positive")
    with get_recipe_db() as conn:
        conn.execute(
            "INSERT INTO shopping_list_template (household_id, fdc_id, quantity_g, note) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(household_id, fdc_id) DO UPDATE SET "
            "quantity_g = excluded.quantity_g, "
            "note = excluded.note, "
            "updated_at = CURRENT_TIMESTAMP",
            [household_id, body.fdc_id, body.quantity_g, body.note],
        )
    return _template_item_out(body.fdc_id, body.quantity_g, body.note)


@router.put("/template/{fdc_id}", response_model=ShoppingTemplateItemOut)
def update_template_item(
    fdc_id: int,
    body: ShoppingTemplateItemIn,
    household_id: str = DEFAULT_HOUSEHOLD_ID,
):
    """Update an existing baseline item's quantity/note."""
    if body.fdc_id != fdc_id:
        raise HTTPException(400, "fdc_id in path and body must match")
    if body.quantity_g <= 0:
        raise HTTPException(400, "quantity_g must be positive")
    with get_recipe_db() as conn:
        result = conn.execute(
            "UPDATE shopping_list_template SET quantity_g = ?, note = ?, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE household_id = ? AND fdc_id = ?",
            [body.quantity_g, body.note, household_id, fdc_id],
        )
        if result.rowcount == 0:
            raise HTTPException(404, f"Template item {fdc_id} not found")
    return _template_item_out(fdc_id, body.quantity_g, body.note)


@router.delete("/template/{fdc_id}", status_code=204)
def delete_template_item(
    fdc_id: int,
    household_id: str = DEFAULT_HOUSEHOLD_ID,
):
    with get_recipe_db() as conn:
        conn.execute(
            "DELETE FROM shopping_list_template WHERE household_id = ? AND fdc_id = ?",
            [household_id, fdc_id],
        )


@router.get("/ingredient-units")
def list_ingredient_units():
    """All display-unit overrides, keyed by fdc_id. Used by the template editor
    to show ≈ converted quantities as the user types grams."""
    with get_recipe_db() as conn:
        rows = conn.execute(
            "SELECT fdc_id, display_unit, grams_per_unit, round_step FROM ingredient_units"
        ).fetchall()
    return {
        r["fdc_id"]: {
            "display_unit": r["display_unit"],
            "grams_per_unit": r["grams_per_unit"],
            "round_step": r["round_step"],
        }
        for r in rows
    }
