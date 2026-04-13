"""USDA ingredient search + user pantry (promoted ingredients).

The curated list (`main.common_ingredients`) is a dbt seed and is read-only from the API.
Users can promote any USDA row into their `pantry_ingredients` (SQLite), and all
ingredient endpoints UNION the two sources at query time.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.database import get_connection as get_duckdb
from api.recipe_db import get_recipe_db

router = APIRouter(tags=["ingredients"])


# Map USDA food_group -> our curated category enum
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


def load_pantry_fdc_ids() -> set[int]:
    with get_recipe_db() as conn:
        return {r["fdc_id"] for r in conn.execute("SELECT fdc_id FROM pantry_ingredients").fetchall()}


def load_aliases() -> dict[int, int]:
    """Return {alias_fdc_id → canonical_fdc_id} mapping.

    Use `resolve_fdc_id(fid)` to dereference a possibly-aliased id to its canonical.
    """
    with get_recipe_db() as conn:
        rows = conn.execute(
            "SELECT alias_fdc_id, canonical_fdc_id FROM ingredient_aliases"
        ).fetchall()
    return {r["alias_fdc_id"]: r["canonical_fdc_id"] for r in rows}


def resolve_fdc_id(fdc_id: int, aliases: dict[int, int] | None = None) -> int:
    """Dereference an fdc_id through the alias chain. Safe against cycles."""
    if aliases is None:
        aliases = load_aliases()
    seen: set[int] = set()
    current = fdc_id
    while current in aliases and current not in seen:
        seen.add(current)
        current = aliases[current]
    return current


def load_all_curated_meta() -> dict[int, dict]:
    """Return {fdc_id: {simple_name, category, subcategory}} for dbt seed ∪ pantry,
    with aliased ids excluded (they resolve to their canonical at lookup time).

    Pantry entries override dbt seed entries on conflict.
    """
    result: dict[int, dict] = {}
    with get_duckdb() as conn:
        rows = conn.execute(
            "SELECT fdc_id, simple_name, category, subcategory FROM main.common_ingredients"
        ).fetchall()
    for r in rows:
        result[r[0]] = {"simple_name": r[1], "category": r[2], "subcategory": r[3]}

    with get_recipe_db() as conn:
        rows = conn.execute(
            "SELECT fdc_id, simple_name, category, subcategory FROM pantry_ingredients"
        ).fetchall()
    for r in rows:
        result[r["fdc_id"]] = {
            "simple_name": r["simple_name"],
            "category": r["category"],
            "subcategory": r["subcategory"],
        }

    # Remove aliased ids — they shouldn't appear in the picker or search results.
    aliases = load_aliases()
    for alias_id in aliases:
        result.pop(alias_id, None)
    return result


# --- USDA search ---


class UsdaSearchResult(BaseModel):
    fdc_id: int
    name: str
    food_group: str | None
    mapped_category: str
    energy_kcal_100g: float | None
    proteins_100g: float | None
    in_pantry: bool


@router.get("/ingredients/usda-search", response_model=list[UsdaSearchResult])
def usda_search(q: str, limit: int = 50):
    q = q.strip()
    if len(q) < 2:
        return []
    like = f"%{q.lower()}%"
    with get_duckdb() as conn:
        rows = conn.execute(
            "SELECT fdc_id, name, food_group, energy_kcal_100g, proteins_100g "
            "FROM usda.ingredients "
            "WHERE lower(name) LIKE ? "
            "ORDER BY length(name), name "
            "LIMIT ?",
            [like, limit],
        ).fetchall()

    pantry_ids = load_pantry_fdc_ids()
    curated_ids = set()
    with get_duckdb() as conn:
        curated_ids = {r[0] for r in conn.execute(
            "SELECT fdc_id FROM main.common_ingredients"
        ).fetchall()}

    return [
        UsdaSearchResult(
            fdc_id=r[0],
            name=r[1],
            food_group=r[2],
            mapped_category=map_food_group(r[2]),
            energy_kcal_100g=r[3],
            proteins_100g=r[4],
            in_pantry=(r[0] in pantry_ids or r[0] in curated_ids),
        )
        for r in rows
    ]


# --- Pantry CRUD ---


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
def list_pantry():
    with get_recipe_db() as conn:
        rows = conn.execute(
            "SELECT fdc_id, simple_name, category, subcategory FROM pantry_ingredients "
            "ORDER BY category, simple_name"
        ).fetchall()
    return [PantryEntry(**dict(r)) for r in rows]


@router.post("/pantry", response_model=PantryEntry, status_code=201)
def add_to_pantry(body: PantryAdd):
    with get_duckdb() as conn:
        row = conn.execute(
            "SELECT fdc_id, name, food_group FROM usda.ingredients WHERE fdc_id = ?",
            [body.fdc_id],
        ).fetchone()
    if not row:
        raise HTTPException(404, f"USDA ingredient {body.fdc_id} not found")

    simple_name = (body.simple_name or row[1]).strip()
    category = body.category or map_food_group(row[2])
    if category not in VALID_CATEGORIES:
        raise HTTPException(400, f"Invalid category '{category}'")

    with get_recipe_db() as conn:
        conn.execute(
            "INSERT INTO pantry_ingredients (fdc_id, simple_name, category, subcategory) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(fdc_id) DO UPDATE SET "
            "simple_name = excluded.simple_name, "
            "category = excluded.category, "
            "subcategory = excluded.subcategory",
            [body.fdc_id, simple_name, category, body.subcategory],
        )
    return PantryEntry(
        fdc_id=body.fdc_id,
        simple_name=simple_name,
        category=category,
        subcategory=body.subcategory,
    )


@router.delete("/pantry/{fdc_id}", status_code=204)
def remove_from_pantry(fdc_id: int):
    with get_recipe_db() as conn:
        conn.execute("DELETE FROM pantry_ingredients WHERE fdc_id = ?", [fdc_id])
