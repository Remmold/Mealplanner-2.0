"""In-memory cache of the global ingredient catalog.

The catalog (curated pantry + aliases + unit overrides) is global, read-only
to users, mutated only by admin scripts. Caching it in memory at startup
turns every lookup into a Python dict access instead of a DB round-trip,
which matters because these helpers are called per-ingredient inside every
recipe / shopping list / chat tool call.

Refresh by restarting the backend (or expose a future /admin/reload-catalog
endpoint when the admin surface lands).
"""

from __future__ import annotations

from api.db import get_pool


_pantry: dict[int, dict] = {}     # fdc_id -> {simple_name, category, subcategory}
_aliases: dict[int, int] = {}     # alias_fdc_id -> canonical_fdc_id
_units: dict[int, dict] = {}      # fdc_id -> {display_unit, grams_per_unit, round_step}


async def load_all() -> None:
    """Load the global catalog from Postgres. Call once at app startup."""
    global _pantry, _aliases, _units

    pool = get_pool()
    async with pool.acquire() as conn:
        pantry_rows = await conn.fetch(
            "SELECT fdc_id, simple_name, category, subcategory "
            "FROM hearth.pantry_ingredients"
        )
        alias_rows = await conn.fetch(
            "SELECT alias_fdc_id, canonical_fdc_id FROM hearth.ingredient_aliases"
        )
        unit_rows = await conn.fetch(
            "SELECT fdc_id, display_unit, grams_per_unit, round_step "
            "FROM hearth.ingredient_units"
        )

    _pantry = {
        r["fdc_id"]: {
            "simple_name": r["simple_name"],
            "category": r["category"],
            "subcategory": r["subcategory"],
        }
        for r in pantry_rows
    }
    _aliases = {r["alias_fdc_id"]: r["canonical_fdc_id"] for r in alias_rows}
    _units = {
        r["fdc_id"]: {
            "display_unit": r["display_unit"],
            "grams_per_unit": float(r["grams_per_unit"]),
            "round_step": float(r["round_step"]),
        }
        for r in unit_rows
    }

    # Aliased ids should never appear in the picker or search results -
    # the user sees only the canonical entry.
    for alias_id in _aliases:
        _pantry.pop(alias_id, None)

    print(
        f"[catalog] loaded pantry={len(_pantry)} aliases={len(_aliases)} units={len(_units)}"
    )


def get_pantry() -> dict[int, dict]:
    return _pantry


def get_aliases() -> dict[int, int]:
    return _aliases


def get_units() -> dict[int, dict]:
    return _units


def pantry_fdc_ids() -> set[int]:
    return set(_pantry.keys())


def resolve_fdc_id(fdc_id: int) -> int:
    """Dereference an fdc_id through the alias chain. Safe against cycles."""
    seen: set[int] = set()
    current = fdc_id
    while current in _aliases and current not in seen:
        seen.add(current)
        current = _aliases[current]
    return current
