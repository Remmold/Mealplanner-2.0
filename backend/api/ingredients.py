"""USDA ingredient search + (admin-flavoured) pantry CRUD.

The curated pantry is now a global Postgres table. Reads use an in-memory
cache (api.catalog_cache); writes go through the asyncpg pool.

Promote (/pantry POST) and delete (/pantry DELETE) are technically
admin-only in the design doc, but for v1 we leave them accessible to any
authenticated user — pantry curation is low-risk, and locking it down
adds an admin surface we haven't built yet. Restart the backend to
refresh the in-memory cache after any pantry mutation.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api import catalog_cache
from api.auth import CurrentUser, get_current_user
from api.db import get_pool

router = APIRouter(tags=["ingredients"])


# ----------------------------------------------------------------------------
# Category mapping kept for any code still consulting USDA food_group values
# (e.g. the shopping-list generator's fallback grouping).
# ----------------------------------------------------------------------------

FOOD_GROUP_MAP = {
    "Dairy and Egg Products": "Dairy & Eggs",
    "Poultry Products": "Meat & Poultry",
    "Beef Products": "Meat & Poultry",
    "Pork Products": "Meat & Poultry",
    "Lamb, Veal, and Game Products": "Meat & Poultry",
    "Sausages and Luncheon Meats": "Meat & Poultry",
    "Finfish and Shellfish Products": "Fish & Seafood",
    "Vegetables and Vegetable Products": "Vegetables",
    "Fruits and Fruit Juices": "Fruits",
    "Cereal Grains and Pasta": "Grains",
    "Baked Products": "Grains",
    "Breakfast Cereals": "Grains",
    "Legumes and Legume Products": "Legumes & Nuts",
    "Nut and Seed Products": "Legumes & Nuts",
    "Fats and Oils": "Oils & Fats",
    "Spices and Herbs": "Seasonings",
    "Soups, Sauces, and Gravies": "Sauces & Condiments",
}

VALID_CATEGORIES = {
    "Dairy & Eggs", "Fish & Seafood", "Fruits", "Grains", "Legumes & Nuts",
    "Meat & Poultry", "Oils & Fats", "Other", "Protein", "Sauces & Condiments",
    "Seasonings", "Vegetables",
}


def map_food_group(food_group: str | None) -> str:
    if not food_group:
        return "Other"
    return FOOD_GROUP_MAP.get(food_group, "Other")


# ----------------------------------------------------------------------------
# Sync helpers — back-compat with code that imports these names from
# `api.ingredients`. They now read from the in-memory catalog cache.
# ----------------------------------------------------------------------------

def load_pantry_fdc_ids() -> set[int]:
    return catalog_cache.pantry_fdc_ids()


def load_aliases() -> dict[int, int]:
    return catalog_cache.get_aliases()


def resolve_fdc_id(fdc_id: int, aliases: dict[int, int] | None = None) -> int:
    # Ignore the optional `aliases` arg — cache is the single source of truth.
    return catalog_cache.resolve_fdc_id(fdc_id)


def load_all_curated_meta() -> dict[int, dict]:
    """{fdc_id: {simple_name, category, subcategory}} for the global catalog.

    Matches the shape the legacy DuckDB-based version returned, including
    the post-alias dereference (alias ids are excluded by the cache loader).
    """
    return catalog_cache.get_pantry()


# ----------------------------------------------------------------------------
# USDA search (Postgres + ILIKE)
# ----------------------------------------------------------------------------

class UsdaSearchResult(BaseModel):
    fdc_id: int
    name: str
    food_group: str | None
    mapped_category: str
    energy_kcal_100g: float | None
    proteins_100g: float | None
    in_pantry: bool


@router.get("/ingredients/usda-search", response_model=list[UsdaSearchResult])
async def usda_search(q: str, limit: int = 50):
    q = q.strip()
    if len(q) < 2:
        return []
    like = f"%{q.lower()}%"

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT fdc_id, description, food_group, energy_kcal, protein_g
            FROM hearth.usda_ingredients
            WHERE lower(description) LIKE $1
            ORDER BY length(description), description
            LIMIT $2
            """,
            like, limit,
        )

    pantry_ids = catalog_cache.pantry_fdc_ids()

    return [
        UsdaSearchResult(
            fdc_id=r["fdc_id"],
            name=r["description"],
            food_group=r["food_group"],
            mapped_category=map_food_group(r["food_group"]),
            energy_kcal_100g=(float(r["energy_kcal"]) if r["energy_kcal"] is not None else None),
            proteins_100g=(float(r["protein_g"]) if r["protein_g"] is not None else None),
            in_pantry=(r["fdc_id"] in pantry_ids),
        )
        for r in rows
    ]


# ----------------------------------------------------------------------------
# Pantry CRUD (Postgres-backed)
# ----------------------------------------------------------------------------

class PantryAdd(BaseModel):
    fdc_id: int
    simple_name: str | None = None
    category: str | None = None
    subcategory: str | None = None


class PantryEntry(BaseModel):
    fdc_id: int
    simple_name: str
    category: str
    subcategory: str | None = None


@router.get("/pantry", response_model=list[PantryEntry])
async def list_pantry():
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT fdc_id, simple_name, category, subcategory "
            "FROM hearth.pantry_ingredients "
            "ORDER BY category, simple_name"
        )
    return [
        PantryEntry(
            fdc_id=r["fdc_id"],
            simple_name=r["simple_name"],
            category=r["category"],
            subcategory=r["subcategory"],
        )
        for r in rows
    ]


@router.post("/pantry", response_model=PantryEntry, status_code=201)
async def add_to_pantry(
    body: PantryAdd,
    _user: CurrentUser = Depends(get_current_user),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        usda_row = await conn.fetchrow(
            "SELECT fdc_id, description, food_group "
            "FROM hearth.usda_ingredients WHERE fdc_id = $1",
            body.fdc_id,
        )
        if usda_row is None:
            raise HTTPException(404, f"USDA ingredient {body.fdc_id} not found")

        simple_name = (body.simple_name or usda_row["description"]).strip()
        category = body.category or map_food_group(usda_row["food_group"])
        if category not in VALID_CATEGORIES:
            raise HTTPException(400, f"Invalid category '{category}'")

        await conn.execute(
            """
            INSERT INTO hearth.pantry_ingredients
                (fdc_id, simple_name, category, subcategory)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (fdc_id) DO UPDATE SET
                simple_name = excluded.simple_name,
                category    = excluded.category,
                subcategory = excluded.subcategory
            """,
            body.fdc_id, simple_name, category, body.subcategory,
        )

    # Reflect into the in-memory cache so subsequent reads see the change
    # without requiring a backend restart.
    catalog_cache.get_pantry()[body.fdc_id] = {
        "simple_name": simple_name,
        "category": category,
        "subcategory": body.subcategory,
    }

    return PantryEntry(
        fdc_id=body.fdc_id,
        simple_name=simple_name,
        category=category,
        subcategory=body.subcategory,
    )


@router.delete("/pantry/{fdc_id}", status_code=204)
async def remove_from_pantry(
    fdc_id: int,
    _user: CurrentUser = Depends(get_current_user),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM hearth.pantry_ingredients WHERE fdc_id = $1",
            fdc_id,
        )
    catalog_cache.get_pantry().pop(fdc_id, None)
