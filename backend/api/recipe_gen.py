"""LLM-powered recipe generation using PydanticAI + OpenAI (Postgres-backed)."""

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel
from pydantic_ai import Agent

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class GeneratedIngredient(BaseModel):
    fdc_id: int
    name: str
    quantity_g: float


class GeneratedRecipe(BaseModel):
    name: str
    ingredients: list[GeneratedIngredient]
    instructions: list[str]


# Nutrition for the global catalog is immutable until restart — cache it
# once on the first tool call and reuse.
_NUTRI_CACHE: dict[int, dict] | None = None


async def _fetch_nutri(fdc_ids: list[int]) -> dict[int, dict]:
    if not fdc_ids:
        return {}
    from api.db import get_pool
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT fdc_id, energy_kcal, protein_g, carbs_g, fat_g
            FROM hearth.usda_ingredients
            WHERE fdc_id = ANY($1::int[])
            """,
            fdc_ids,
        )
    return {
        r["fdc_id"]: {
            "kcal":    float(r["energy_kcal"]) if r["energy_kcal"] is not None else None,
            "protein": float(r["protein_g"])   if r["protein_g"]   is not None else None,
            "carbs":   float(r["carbs_g"])     if r["carbs_g"]     is not None else None,
            "fat":     float(r["fat_g"])       if r["fat_g"]       is not None else None,
        }
        for r in rows
    }


async def _load_all_ingredients() -> list[dict]:
    """Curated pantry joined with USDA nutrition (cached)."""
    from api.ingredients import load_all_curated_meta

    meta = load_all_curated_meta()
    if not meta:
        return []

    global _NUTRI_CACHE
    if _NUTRI_CACHE is None:
        _NUTRI_CACHE = await _fetch_nutri(list(meta.keys()))
    nutri = _NUTRI_CACHE

    return [
        {
            "fdc_id":  fid,
            "name":    info["simple_name"],
            "category": info["category"],
            "kcal":    nutri.get(fid, {}).get("kcal"),
            "protein": nutri.get(fid, {}).get("protein"),
            "carbs":   nutri.get(fid, {}).get("carbs"),
            "fat":     nutri.get(fid, {}).get("fat"),
        }
        for fid, info in meta.items()
    ]


async def _search_usda_fallback(query: str, limit: int = 25) -> list[dict]:
    """Search the full USDA table when curated has no hits."""
    from api.db import get_pool
    from api.ingredients import map_food_group

    like = f"%{query.lower()}%"
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT fdc_id, description, food_group,
                   energy_kcal, protein_g, carbs_g, fat_g
            FROM hearth.usda_ingredients
            WHERE lower(description) LIKE $1
            ORDER BY length(description), description
            LIMIT $2
            """,
            like, limit,
        )
    return [
        {
            "fdc_id":  r["fdc_id"],
            "name":    r["description"],
            "category": map_food_group(r["food_group"]),
            "kcal":    float(r["energy_kcal"]) if r["energy_kcal"] is not None else None,
            "protein": float(r["protein_g"])   if r["protein_g"]   is not None else None,
            "carbs":   float(r["carbs_g"])     if r["carbs_g"]     is not None else None,
            "fat":     float(r["fat_g"])       if r["fat_g"]       is not None else None,
        }
        for r in rows
    ]


_MODEL_RAW = os.getenv("OPENAI_RECIPE_MODEL", "gpt-4o-mini")
# Prefix with "openai:" if the user gave a bare model name. The .env.example
# encourages "gpt-4o-mini"; PydanticAI normally infers the provider, but
# being explicit removes a class of "agent silently picked wrong provider"
# bugs.
_MODEL = _MODEL_RAW if ":" in _MODEL_RAW else f"openai:{_MODEL_RAW}"

agent = Agent(
    _MODEL,
    output_type=GeneratedRecipe,
    system_prompt=(
        "You are an experienced chef generating detailed, restaurant-quality recipes "
        "for a meal planning app. You MUST use the search_ingredients tool to find "
        "available ingredients and their fdc_id values — never invent fdc_id values. "
        "Call the tool multiple times with different queries to build a complete pantry "
        "(proteins, vegetables, aromatics, fats, acids, herbs, spices, seasonings). "
        "\n\nRecipe requirements:\n"
        "- Include 8-15 ingredients for depth of flavor — do not skip aromatics, "
        "  seasonings (salt, pepper, etc.), fats/oils, or acids. A recipe with only "
        "  3-5 ingredients is unacceptable unless the user explicitly asks for minimalism.\n"
        "- Realistic per-serving quantities in grams, scaled for 2-4 servings total.\n"
        "- Instructions must be 6-12 detailed steps. Each step should specify:\n"
        "  * Technique (sear, simmer, deglaze, fold, rest, etc.)\n"
        "  * Temperature (e.g. 'medium-high heat', '180°C oven')\n"
        "  * Timing (e.g. '4-5 minutes until golden')\n"
        "  * Sensory cues (color, aroma, texture) so the cook knows when to move on.\n"
        "- Mention seasoning and tasting at appropriate points.\n"
        "- Prefer building flavor in stages (bloom spices, brown proteins, build fond) "
        "  rather than dumping everything into a pot.\n"
        "\nName the dish evocatively, not generically ('Lemon-Herb Braised Chicken' "
        "not 'Chicken Recipe')."
    ),
)


@agent.tool_plain
async def search_ingredients(query: str) -> str:
    """Search available ingredients by name or category.

    Searches the curated pantry first (preferred); falls back to the full
    USDA database (~8k items) when curated has no hits. Returns fdc_id,
    name, category, and basic nutrition per 100g."""
    all_ingredients = await _load_all_ingredients()
    query_lower = query.lower()
    matches = [
        ing for ing in all_ingredients
        if query_lower in ing["name"].lower() or query_lower in ing["category"].lower()
    ]
    source = "curated"
    if not matches:
        matches = await _search_usda_fallback(query)
        source = "usda"
    if not matches:
        return f"No ingredients found for '{query}'. Try a broader search."

    lines = [f"Source: {source}"]
    for ing in matches:
        lines.append(
            f"fdc_id={ing['fdc_id']} | {ing['name']} | {ing['category']} | "
            f"{ing['kcal']} kcal, {ing['protein']}g protein, "
            f"{ing['carbs']}g carbs, {ing['fat']}g fat per 100g"
        )
    return "\n".join(lines)


async def generate_recipe(prompt: str) -> GeneratedRecipe:
    """Generate a recipe from a user prompt."""
    result = await agent.run(prompt)
    return result.output
