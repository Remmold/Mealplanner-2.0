"""Starter recipe seeding — now driven by hearth.public_recipes.

The "Import starter recipes" button on the Recipes-tab empty state, and the
auto-seed on ProfileWizard completion, both call this. We pick rows from the
public pool (source = 'starter_corpus') that fit the household's profile and
copy them in. Idempotent on public_origin_id.

The corpus JSON file is no longer the source — `scripts.seed_public_pool`
ingests it into the pool once, and from then on this module reads from the
DB. That unifies the discovery surface: an LLM-generated recipe that lands
in the pool can also flow back out through the starter-import button.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from api.auth import CurrentUser, get_current_user
from api.db import get_current_household_id, service_tx
from api.profile import HouseholdProfile, load_profile
from api.public_pool import copy_to_household

log = logging.getLogger("starter_seed")

router = APIRouter(prefix="/recipes", tags=["recipes"])


def _matches_profile(recipe: dict, profile: HouseholdProfile) -> bool:
    """Reject recipes that violate hard profile constraints."""
    dietary = recipe.get("dietary") or []
    if "vegetarian" in profile.dietary and "vegetarian" not in dietary:
        return False
    if "vegan" in profile.dietary and "vegan" not in dietary:
        return False
    if profile.typical_cook_time_min:
        time_min = recipe.get("time_min") or 0
        if time_min > int(profile.typical_cook_time_min * 1.5):
            return False
    return True


def _score(recipe: dict, profile: HouseholdProfile) -> int:
    score = 0
    cuisines = {c.lower() for c in (recipe.get("cuisine") or [])}
    for c in profile.cuisines:
        if c.lower() in cuisines:
            score += 5
    if profile.typical_cook_time_min and (recipe.get("time_min") or 999) <= profile.typical_cook_time_min:
        score += 3
    pref = profile.batch_cook_preference
    meal_type = recipe.get("meal_type")
    if pref == "heavy" and meal_type == "dinner":
        score += 2
    return score


async def seed_recipes_for_household(household_id: str, count: int = 12) -> list[str]:
    """Insert profile-matched starter recipes (from the public pool) into a
    household. Returns the list of names actually created."""
    profile = await load_profile(household_id)

    # Pull the whole starter slice of the pool — it's small (~60 rows) so
    # paginating/filtering server-side gains us nothing. Score in Python.
    async with service_tx() as conn:
        rows = await conn.fetch(
            """
            SELECT id::text AS id, name, meal_type, cuisine, dietary, time_min
            FROM hearth.public_recipes
            WHERE source = 'starter_corpus'
            """,
        )
    pool = [
        {
            "id": r["id"],
            "name": r["name"],
            "meal_type": r["meal_type"],
            "cuisine": list(r["cuisine"] or []),
            "dietary": list(r["dietary"] or []),
            "time_min": r["time_min"],
        }
        for r in rows
    ]

    matched = [r for r in pool if _matches_profile(r, profile)]
    if not matched:
        # Profile too strict — relax everything but the dietary mode.
        matched = [
            r for r in pool
            if not ("vegetarian" in profile.dietary and "vegetarian" not in r["dietary"])
        ]
    matched.sort(key=lambda r: _score(r, profile), reverse=True)

    # Balance across meal types so the user gets breakfast + lunch + dinner.
    by_type: dict[str, list] = {}
    for r in matched:
        by_type.setdefault(r["meal_type"] or "any", []).append(r)
    per_type = max(1, count // max(1, len(by_type)))

    picks: list[dict] = []
    seen: set[str] = set()
    for recipes in by_type.values():
        for r in recipes[:per_type]:
            if r["id"] not in seen:
                picks.append(r)
                seen.add(r["id"])
    if len(picks) < count:
        for r in matched:
            if r["id"] in seen:
                continue
            picks.append(r)
            seen.add(r["id"])
            if len(picks) >= count:
                break

    created: list[str] = []
    for r in picks[:count]:
        rid, name = await copy_to_household(r["id"], household_id, schedule_image_gen=True)
        if rid and name and name not in created:
            created.append(name)

    log.info("[starter_seed] household=%s created=%d", household_id, len(created))
    return created


@router.post("/seed-starters")
async def seed_starters(
    count: int = 12,
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    """Seed N starter recipes (default 12) matched to the household profile,
    sourced from hearth.public_recipes."""
    _ = user
    created = await seed_recipes_for_household(household_id, count=count)
    return {"created": created, "count": len(created)}
