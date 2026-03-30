"""LLM-powered recipe generation using PydanticAI + OpenAI."""

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


agent = Agent(
    "openai:o4-mini",
    output_type=GeneratedRecipe,
    system_prompt=(
        "You are a recipe generator for a meal planning app. "
        "When the user asks for a recipe, you MUST use the search_ingredients tool "
        "to find available ingredients and their fdc_id values. "
        "Only use ingredients returned by the tool — never invent fdc_id values. "
        "Return a complete recipe with realistic quantities in grams. "
        "Keep instructions concise (3-8 steps)."
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
