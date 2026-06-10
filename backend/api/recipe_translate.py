"""Per-locale recipe content.

Recipes carry a `translations` jsonb — {"en": {"name","instructions"}, "sv": {...}}
— alongside the canonical name/instructions. Reads pick the active UI locale
(falling back to the base columns); `ensure_recipe_translation` lazily fills a
missing locale in the background. Mirrors the pydantic-ai pattern in recipe_gen.
"""
from __future__ import annotations

import asyncio
import logging
import os

from pydantic import BaseModel
from pydantic_ai import Agent

from api.db import service_tx

log = logging.getLogger("recipe_translate")

_MODEL_RAW = os.getenv("OPENAI_RECIPE_MODEL", "gpt-4o-mini")
_MODEL = _MODEL_RAW if ":" in _MODEL_RAW else f"openai:{_MODEL_RAW}"

_LANG = {"en": "English", "sv": "Swedish"}
SUPPORTED = ("en", "sv")


class _Translation(BaseModel):
    name: str
    instructions: list[str]


_translator = Agent(
    _MODEL,
    output_type=_Translation,
    system_prompt=(
        "You translate a recipe's NAME and INSTRUCTION steps into a target "
        "language for a meal-planning app.\n"
        "- Keep EXACTLY the same number of steps, in the same order.\n"
        "- Preserve all quantities, temperatures (°C) and times.\n"
        "- Translate ingredient and technique words naturally.\n"
        "- Do NOT add, remove, merge, or renumber steps, and add no commentary.\n"
        "- If the text is already in the target language, return it unchanged."
    ),
)


async def translate_recipe(name: str, instructions: list[str], target: str) -> dict:
    """Translate name + steps into `target` ('en'|'sv'). Returns {name, instructions}."""
    lang = _LANG.get(target, target)
    prompt = (
        f"Target language: {lang}.\n\n"
        f"NAME: {name}\n\n"
        f"STEPS (JSON array — return the same count):\n{instructions!r}"
    )
    out = (await _translator.run(prompt)).output
    steps = out.instructions if len(out.instructions) == len(instructions) else instructions
    return {"name": (out.name or name).strip(), "instructions": steps}


def localized(name: str, instructions: list, translations: dict | None, locale: str):
    """Pick the locale's (name, instructions) from translations, else the base."""
    entry = (translations or {}).get(locale)
    if isinstance(entry, dict) and entry.get("name"):
        return entry["name"], (entry.get("instructions") or instructions)
    return name, instructions


async def _do_ensure(recipe_id: str, locale: str) -> None:
    if locale not in SUPPORTED:
        return
    try:
        async with service_tx() as conn:
            row = await conn.fetchrow(
                "SELECT name, instructions, translations "
                "FROM hearth.recipes WHERE id = $1::uuid",
                recipe_id,
            )
            if row is None:
                return
            translations = row["translations"] or {}
            existing = translations.get(locale)
            if isinstance(existing, dict) and existing.get("name"):
                return  # already filled
            instr = row["instructions"] if isinstance(row["instructions"], list) else []
            tr = await translate_recipe(row["name"], instr, locale)
            await conn.execute(
                "UPDATE hearth.recipes SET translations = translations || $1::jsonb "
                "WHERE id = $2::uuid",
                {locale: tr}, recipe_id,
            )
            log.info("[recipe_translate] filled %s for recipe %s", locale, recipe_id)
    except Exception:
        log.exception("[recipe_translate] ensure failed for %s / %s", recipe_id, locale)


_BG_TASKS: set[asyncio.Task] = set()


def ensure_recipe_translation(recipe_id: str, locale: str) -> None:
    """Fire-and-forget: fill a missing locale's translation for one recipe."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_do_ensure(recipe_id, locale))
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
