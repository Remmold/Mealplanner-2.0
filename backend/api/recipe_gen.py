"""LLM-powered recipe generation using PydanticAI + OpenAI."""

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel
from pydantic_ai import Agent

from api.database import get_connection

# Ensure .env is loaded (for OPENAI_API_KEY)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class GeneratedIngredient(BaseModel):
    fdc_id: int
    name: str
    quantity_g: float


class GeneratedRecipe(BaseModel):
    name: str
    ingredients: list[GeneratedIngredient]
    instructions: list[str]


def _load_all_ingredients() -> list[dict]:
    """Load curated ingredients (dbt seed ∪ pantry) joined with USDA nutrition."""
    from api.ingredients import load_all_curated_meta
    meta = load_all_curated_meta()
    if not meta:
        return []
    fdc_ids = list(meta.keys())
    placeholders = ", ".join(["?"] * len(fdc_ids))
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT fdc_id, energy_kcal_100g, proteins_100g, carbohydrates_100g, fat_100g "
            f"FROM usda.ingredients WHERE fdc_id IN ({placeholders})",
            fdc_ids,
        ).fetchall()
    nutri = {r[0]: r for r in rows}
    return [
        {
            "fdc_id": fid,
            "name": info["simple_name"],
            "category": info["category"],
            "kcal": (nutri.get(fid) or [None, None])[1],
            "protein": (nutri.get(fid) or [None, None, None])[2],
            "carbs": (nutri.get(fid) or [None, None, None, None])[3],
            "fat": (nutri.get(fid) or [None, None, None, None, None])[4],
        }
        for fid, info in meta.items()
    ]


def _search_usda_fallback(query: str, limit: int = 25) -> list[dict]:
    """Search the full USDA table when curated has no hits."""
    like = f"%{query.lower()}%"
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT fdc_id, name, food_group, energy_kcal_100g, proteins_100g, "
            "carbohydrates_100g, fat_100g FROM usda.ingredients "
            "WHERE lower(name) LIKE ? ORDER BY length(name), name LIMIT ?",
            [like, limit],
        ).fetchall()
    from api.ingredients import map_food_group
    return [
        {
            "fdc_id": r[0], "name": r[1], "category": map_food_group(r[2]),
            "kcal": r[3], "protein": r[4], "carbs": r[5], "fat": r[6],
        }
        for r in rows
    ]


_MODEL = os.getenv("OPENAI_RECIPE_MODEL", "openai:gpt-4o")

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
def search_ingredients(query: str) -> str:
    """Search available ingredients by name or category.

    Searches the curated pantry first (preferred). If no hits, falls back
    to the full USDA database (~8000 items). Returns fdc_id, name, category,
    and basic nutrition per 100g.
    """
    all_ingredients = _load_all_ingredients()
    query_lower = query.lower()
    matches = [
        ing for ing in all_ingredients
        if query_lower in ing["name"].lower() or query_lower in ing["category"].lower()
    ]
    source = "curated"
    if not matches:
        matches = _search_usda_fallback(query)
        source = "usda"
    if not matches:
        return f"No ingredients found for '{query}'. Try a broader search."

    lines = [f"Source: {source}"]
    for ing in matches:
        lines.append(
            f"fdc_id={ing['fdc_id']} | {ing['name']} | {ing['category']} | "
            f"{ing['kcal']} kcal, {ing['protein']}g protein, {ing['carbs']}g carbs, {ing['fat']}g fat per 100g"
        )
    return "\n".join(lines)


async def generate_recipe(prompt: str) -> GeneratedRecipe:
    """Generate a recipe from a user prompt."""
    result = await agent.run(prompt)
    return result.output
