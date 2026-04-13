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
    """Load the curated ingredient list from DuckDB."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT ci.fdc_id, ci.simple_name, ci.category, "
            "u.energy_kcal_100g, u.proteins_100g, u.carbohydrates_100g, u.fat_100g "
            "FROM main.common_ingredients ci "
            "JOIN usda.ingredients u ON u.fdc_id = ci.fdc_id "
            "ORDER BY ci.category, ci.simple_name"
        ).fetchall()
    return [
        {
            "fdc_id": r[0], "name": r[1], "category": r[2],
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

    Use this to find ingredients and their fdc_id values.
    You can search by name (e.g. 'chicken') or category (e.g. 'Vegetables').
    Returns fdc_id, name, category, and basic nutrition per 100g.
    """
    all_ingredients = _load_all_ingredients()
    query_lower = query.lower()
    matches = [
        ing for ing in all_ingredients
        if query_lower in ing["name"].lower() or query_lower in ing["category"].lower()
    ]
    if not matches:
        return f"No ingredients found for '{query}'. Try a broader search."

    lines = []
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
