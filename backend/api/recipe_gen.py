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


# USDA food_groups that hold branded / pre-prepared / restaurant items —
# never useful as a recipe building block. The LLM would otherwise sometimes
# pick "DENNY'S, french fries" when searching for "potato".
_BLOCKED_FOOD_GROUPS: tuple[str, ...] = (
    "Restaurant Foods",
    "Fast Foods",
    "Meals, Entrees, and Side Dishes",
    "Snacks",
    "Baby Foods",
    "American Indian/Alaska Native Foods",
)


async def _search_usda_fallback(query: str, limit: int = 25) -> list[dict]:
    """Search the full USDA table when curated has no hits. Filters out
    branded / restaurant / pre-prepared entries that look real but aren't
    suitable as recipe ingredients."""
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
              AND food_group <> ALL($2::text[])
              -- skip rows whose description starts with an UPPERCASE brand
              -- like "DENNY'S, ..." or "ON THE BORDER, ..."
              AND NOT description ~ '^[A-Z][A-Z'' ]{2,},'
            ORDER BY length(description), description
            LIMIT $3
            """,
            like, list(_BLOCKED_FOOD_GROUPS), limit,
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
        "not 'Chicken Recipe').\n"
        "\nLanguage: write the recipe name, ingredient names, and all instruction "
        "steps in the SAME language as the user's request. If the request is in "
        "Swedish, write the whole recipe in Swedish; if in English, write it in "
        "English. (The fdc_id values you look up are language-agnostic — only the "
        "human-readable text follows the request's language.)"
    ),
)


async def _do_search(query: str) -> str:
    """Shared ingredient-search body used by both the text and vision agents."""
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


@agent.tool_plain
async def search_ingredients(query: str) -> str:
    """Search available ingredients by name or category.

    Searches the curated pantry first (preferred); falls back to the full
    USDA database (~8k items) when curated has no hits. Returns fdc_id,
    name, category, and basic nutrition per 100g."""
    return await _do_search(query)


def _avoidance_directive(
    allergies: list[str] | None, dislikes: list[str] | None
) -> str:
    """A hard 'do not use these ingredients' block appended to the prompt.

    Allergies and dislikes come from the household profile and may be written in
    ANY language (often Swedish) — the model is told to interpret them by meaning
    rather than spelling, so 'lök' blocks onion even in an English recipe."""
    allergies = [a for a in (allergies or []) if str(a).strip()]
    dislikes = [d for d in (dislikes or []) if str(d).strip()]
    if not allergies and not dislikes:
        return ""
    lines = [
        "\n\nHOUSEHOLD FOOD RESTRICTIONS — these may be written in another language "
        "(often Swedish); interpret each by MEANING, not spelling (e.g. 'lök' = "
        "onion, 'jordnötter' = peanuts, 'skaldjur' = shellfish, 'laktos' = "
        "lactose/dairy), and apply them to the ingredients you choose regardless "
        "of the recipe's language:",
    ]
    if allergies:
        lines.append(
            "- ALLERGIES (NEVER include these, anything made from them, or close "
            "substitutes — this is a strict safety rule): " + ", ".join(allergies) + "."
        )
    if dislikes:
        lines.append(
            "- DISLIKES (do not use these as ingredients): " + ", ".join(dislikes) + "."
        )
    return "\n".join(lines)


async def generate_recipe(
    prompt: str,
    *,
    allergies: list[str] | None = None,
    dislikes: list[str] | None = None,
) -> GeneratedRecipe:
    """Generate a recipe from a user prompt.

    `allergies`/`dislikes` (from the household profile) are injected as a hard
    avoidance directive so the generated recipe never contains them, in any
    language. Callers that have the profile should always pass them."""
    result = await agent.run(prompt + _avoidance_directive(allergies, dislikes))
    return result.output


# ---- Recipe extraction from photos (vision) ---------------------------------

_VISION_SYSTEM = (
    "You transcribe a recipe from one or more PHOTOS (a cookbook page, a "
    "handwritten card, a printout, or a phone screenshot) into structured form "
    "for a meal-planning app. Reproduce the recipe FAITHFULLY — do not invent.\n"
    "- Use the dish's name as written.\n"
    "- List every ingredient shown, with its quantity converted to GRAMS "
    "(convert cups / tbsp / tsp / pieces sensibly; estimate only when a quantity "
    "is missing or illegible).\n"
    "- You MUST call search_ingredients to map EVERY ingredient to a real fdc_id "
    "— never invent fdc_id values. Search by the core ingredient word.\n"
    "- Reproduce the method as the steps shown; you may lightly clean up grammar "
    "and ordering, but DO NOT add steps or ingredients that aren't in the photos.\n"
    "- If several photos show ONE recipe (an ingredients page + a method page), "
    "merge them. If the photos are unreadable or aren't a recipe, return a recipe "
    "named 'Unreadable' with no ingredients and one instruction saying so.\n"
    "Write the name, ingredient names, and steps in the language requested."
)

vision_agent = Agent(_MODEL, output_type=GeneratedRecipe, system_prompt=_VISION_SYSTEM)


@vision_agent.tool_plain
async def vision_search_ingredients(query: str) -> str:
    """Search available ingredients by name/category; returns fdc_id, name,
    category, and basic nutrition per 100g (same source as the text agent)."""
    return await _do_search(query)


def _prep_image(raw: bytes, max_px: int = 1536) -> bytes:
    """Downscale + re-encode an uploaded photo to JPEG so the vision call stays
    cheap and the format is one OpenAI accepts. Falls back to the raw bytes."""
    try:
        from io import BytesIO
        from PIL import Image
        img = Image.open(BytesIO(raw)).convert("RGB")
        img.thumbnail((max_px, max_px))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception:
        return raw


async def generate_recipe_from_images(
    images: list[bytes], *, locale: str = "en"
) -> GeneratedRecipe:
    """Read a recipe from photo(s) and return it in the SAME structure as
    generate_recipe (ingredients mapped to fdc_ids via search_ingredients)."""
    from pydantic_ai import BinaryContent

    lang = "Swedish" if str(locale).startswith("sv") else "English"
    parts: list = [
        f"Transcribe the recipe shown in these photo(s). Write the name, "
        f"ingredients, and steps in {lang}."
    ]
    for raw in images:
        parts.append(BinaryContent(data=_prep_image(raw), media_type="image/jpeg"))
    result = await vision_agent.run(parts)
    return result.output
