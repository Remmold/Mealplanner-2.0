"""Explore — a Tinder-style recipe discovery deck.

GET  /explore/deck?count=20&slot=breakfast|lunch|dinner|any
  Profile-ranked cards from hearth.public_recipes, excluding cards the user
  has already swiped or imported.

POST /explore/swipe { public_recipe_id, direction: 'like' | 'skip' }
  Logs the swipe. On 'like', copies the recipe into hearth.recipes and
  threshold-updates profile.cuisines from cumulative likes (3 likes in a
  cuisine → cuisine joins the profile).

POST /explore/undo
  Reverses the most-recent swipe. If it was a like, also deletes the imported
  personal copy (unless the user already added it to a plan — guard).

GET  /explore/stats — small counters for UI affordances ("Build a week from
                     your 7 likes").
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth import CurrentUser, get_current_user
from api.db import get_current_household_id, service_tx
from api.profile import HouseholdProfile, load_profile, _save_profile  # type: ignore
from api.public_pool import copy_to_household, pool_recipe_by_id

log = logging.getLogger("explore")

router = APIRouter(prefix="/explore", tags=["explore"])

# Threshold at which a cumulative like-pattern auto-edits the profile.
PROFILE_LEARN_THRESHOLD = 3


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ExploreCard(BaseModel):
    id: str
    name: str
    meal_type: str | None = None
    cuisine: list[str] = []
    dietary: list[str] = []
    time_min: int | None = None
    source: str
    image_path: str | None = None
    ingredients_preview: list[str] = []   # first 6-ish display names
    ingredient_count: int
    step_count: int
    match_reasons: list[str] = []         # 'Greek cuisine match', '30 min fits your tolerance'


class ExploreRecipeIngredient(BaseModel):
    fdc_id: int
    name: str | None = None
    quantity_g: float
    # Optional display override — when present, render '4 hamburger buns'
    # instead of '200g bread'. Computed at endpoint time from
    # hearth.ingredient_units; absent for ingredients where grams remain
    # the most natural unit.
    display_quantity: float | None = None
    display_unit: str | None = None


class ExploreRecipeDetail(BaseModel):
    id: str
    name: str
    meal_type: str | None = None
    cuisine: list[str] = []
    dietary: list[str] = []
    time_min: int | None = None
    source: str
    image_path: str | None = None
    ingredients: list[ExploreRecipeIngredient]
    instructions: list[str]


class SwipeIn(BaseModel):
    public_recipe_id: str
    direction: Literal["like", "skip"]


class SwipeResult(BaseModel):
    saved_recipe_id: str | None = None
    saved_recipe_name: str | None = None
    profile_added_cuisines: list[str] = []


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def _hard_filter(row: dict, profile: HouseholdProfile) -> bool:
    dietary = row.get("dietary") or []
    if "vegetarian" in profile.dietary and "vegetarian" not in dietary:
        return False
    if "vegan" in profile.dietary and "vegan" not in dietary:
        return False
    for allergen in profile.allergies:
        if any(allergen.lower() in (i.get("name") or "").lower() for i in row.get("ingredients") or []):
            return False
    if profile.typical_cook_time_min:
        if (row.get("time_min") or 0) > int(profile.typical_cook_time_min * 1.5):
            return False
    return True


def _score_and_reasons(row: dict, profile: HouseholdProfile, slot: str | None) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    if slot and row.get("meal_type") == slot:
        score += 8
        reasons.append(f"Fits {slot}")
    row_cuisines = {c.lower() for c in (row.get("cuisine") or [])}
    matched_cuisines = [c for c in profile.cuisines if c.lower() in row_cuisines]
    if matched_cuisines:
        score += 5 * len(matched_cuisines)
        reasons.append(f"{', '.join(matched_cuisines).title()} cuisine")
    if profile.typical_cook_time_min and (row.get("time_min") or 999) <= profile.typical_cook_time_min:
        score += 3
        reasons.append(f"≤ {profile.typical_cook_time_min} min")
    if row.get("source") == "llm":
        score += 1  # tiebreak: slight novelty bonus for community LLM gens
    return score, reasons


def _ingredient_previews(ings: list[dict], limit: int = 6) -> list[str]:
    names: list[str] = []
    for ing in ings:
        n = ing.get("name")
        if n and n not in names:
            names.append(n)
        if len(names) >= limit:
            break
    return names


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/deck", response_model=list[ExploreCard])
async def deck(
    count: int = Query(20, ge=1, le=50),
    slot: str | None = Query(None, pattern="^(breakfast|lunch|dinner|any)$"),
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    _ = user
    slot_param: str | None = None if (slot in (None, "any")) else slot

    profile = await load_profile(household_id)

    async with service_tx() as conn:
        rows = await conn.fetch(
            """
            SELECT pr.id::text AS id, pr.name, pr.ingredients, pr.instructions,
                   pr.meal_type, pr.cuisine, pr.dietary, pr.time_min,
                   pr.source, pr.image_path
            FROM hearth.public_recipes pr
            WHERE NOT EXISTS (
                SELECT 1 FROM hearth.recipe_swipes s
                WHERE s.household_id = $1::uuid AND s.public_recipe_id = pr.id
            )
            AND NOT EXISTS (
                SELECT 1 FROM hearth.recipes r
                WHERE r.household_id = $1::uuid AND r.public_origin_id = pr.id
            )
            """,
            household_id,
        )

    candidates: list[dict] = []
    for r in rows:
        d = {
            "id":           r["id"],
            "name":         r["name"],
            "ingredients":  list(r["ingredients"] or []),
            "instructions": list(r["instructions"] or []),
            "meal_type":    r["meal_type"],
            "cuisine":      list(r["cuisine"] or []),
            "dietary":      list(r["dietary"] or []),
            "time_min":     r["time_min"],
            "source":       r["source"],
            "image_path":   r["image_path"],
        }
        if not _hard_filter(d, profile):
            continue
        if slot_param and d["meal_type"] is not None and d["meal_type"] != slot_param:
            # Slot filter is a soft preference unless the user picked a
            # specific one — then it's hard.
            continue
        candidates.append(d)

    scored: list[tuple[int, list[str], dict]] = []
    for d in candidates:
        score, reasons = _score_and_reasons(d, profile, slot_param)
        scored.append((score, reasons, d))
    scored.sort(key=lambda t: t[0], reverse=True)

    out: list[ExploreCard] = []
    for score, reasons, d in scored[:count]:
        out.append(ExploreCard(
            id=d["id"],
            name=d["name"],
            meal_type=d["meal_type"],
            cuisine=d["cuisine"],
            dietary=d["dietary"],
            time_min=d["time_min"],
            source=d["source"],
            image_path=d["image_path"],
            ingredients_preview=_ingredient_previews(d["ingredients"]),
            ingredient_count=len(d["ingredients"]),
            step_count=len(d["instructions"]),
            match_reasons=reasons,
        ))
    return out


@router.get("/recipe/{public_recipe_id}", response_model=ExploreRecipeDetail)
async def recipe_detail(
    public_recipe_id: str,
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    """Full ingredients + instructions for the inspect-before-deciding modal."""
    _ = user, household_id
    from api import catalog_cache
    import math

    async with service_tx() as conn:
        row = await pool_recipe_by_id(conn, public_recipe_id)
    if row is None:
        raise HTTPException(404, "Recipe not in pool")

    units = catalog_cache.get_units()
    enriched: list[ExploreRecipeIngredient] = []
    for ing in row["ingredients"]:
        fdc_id = int(ing["fdc_id"])
        grams = float(ing["quantity_g"])
        u = units.get(fdc_id)
        disp_qty: float | None = None
        disp_unit: str | None = None
        if u and u["grams_per_unit"] > 0:
            raw = grams / u["grams_per_unit"]
            step = u["round_step"] or 1
            # Round to the nearest step; never below the smallest meaningful
            # increment. (1 garlic clove always rounds to >=1 clove.)
            disp_qty = max(step, round(raw / step) * step)
            disp_unit = u["display_unit"]
        enriched.append(ExploreRecipeIngredient(
            fdc_id=fdc_id,
            name=ing.get("name"),
            quantity_g=grams,
            display_quantity=disp_qty,
            display_unit=disp_unit,
        ))

    return ExploreRecipeDetail(
        id=row["id"],
        name=row["name"],
        meal_type=row["meal_type"],
        cuisine=row["cuisine"],
        dietary=row["dietary"],
        time_min=row["time_min"],
        source=row["source"],
        image_path=row["image_path"],
        ingredients=enriched,
        instructions=row["instructions"],
    )


@router.post("/swipe", response_model=SwipeResult)
async def swipe(
    body: SwipeIn,
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    _ = user
    async with service_tx() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM hearth.public_recipes WHERE id = $1::uuid",
            body.public_recipe_id,
        )
        if not exists:
            raise HTTPException(404, "Recipe not in pool")

        await conn.execute(
            """
            INSERT INTO hearth.recipe_swipes (household_id, public_recipe_id, direction)
            VALUES ($1::uuid, $2::uuid, $3)
            ON CONFLICT (household_id, public_recipe_id) DO UPDATE
                SET direction = excluded.direction, created_at = now()
            """,
            household_id, body.public_recipe_id, body.direction,
        )

    if body.direction == "skip":
        return SwipeResult()

    # Like → copy + (maybe) learn.
    recipe_id, recipe_name = await copy_to_household(body.public_recipe_id, household_id)
    added_cuisines = await _threshold_learn(household_id)
    return SwipeResult(
        saved_recipe_id=recipe_id,
        saved_recipe_name=recipe_name,
        profile_added_cuisines=added_cuisines,
    )


@router.post("/undo", response_model=SwipeResult)
async def undo(
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    """Pop the most recent swipe. If it was a like, removes the imported
    personal copy UNLESS that copy was already added to a meal plan."""
    _ = user
    async with service_tx() as conn:
        last = await conn.fetchrow(
            """
            SELECT public_recipe_id::text AS id, direction
            FROM hearth.recipe_swipes
            WHERE household_id = $1::uuid
            ORDER BY created_at DESC LIMIT 1
            """,
            household_id,
        )
        if not last:
            return SwipeResult()

        await conn.execute(
            "DELETE FROM hearth.recipe_swipes "
            "WHERE household_id = $1::uuid AND public_recipe_id = $2::uuid",
            household_id, last["id"],
        )

        if last["direction"] == "like":
            personal = await conn.fetchrow(
                "SELECT id::text AS id FROM hearth.recipes "
                "WHERE household_id = $1::uuid AND public_origin_id = $2::uuid",
                household_id, last["id"],
            )
            if personal:
                used = await conn.fetchval(
                    "SELECT 1 FROM hearth.meal_plan_entries "
                    "WHERE recipe_id = $1::uuid LIMIT 1",
                    personal["id"],
                )
                if not used:
                    await conn.execute(
                        "DELETE FROM hearth.recipes WHERE id = $1::uuid",
                        personal["id"],
                    )

    return SwipeResult()


@router.get("/stats")
async def stats(
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    _ = user
    async with service_tx() as conn:
        likes = await conn.fetchval(
            "SELECT count(*) FROM hearth.recipe_swipes "
            "WHERE household_id = $1::uuid AND direction = 'like'",
            household_id,
        )
        skips = await conn.fetchval(
            "SELECT count(*) FROM hearth.recipe_swipes "
            "WHERE household_id = $1::uuid AND direction = 'skip'",
            household_id,
        )
        pool_size = await conn.fetchval("SELECT count(*) FROM hearth.public_recipes")
    return {"likes": int(likes or 0), "skips": int(skips or 0), "pool_size": int(pool_size or 0)}


# ---------------------------------------------------------------------------
# Threshold-based profile learning
# ---------------------------------------------------------------------------


async def _threshold_learn(household_id: str) -> list[str]:
    """If a cuisine has accumulated PROFILE_LEARN_THRESHOLD likes, append it
    to profile.cuisines. Returns the newly-added cuisines so the UI can
    surface "Added Greek to your cuisines"."""
    async with service_tx() as conn:
        rows = await conn.fetch(
            """
            SELECT unnest(pr.cuisine) AS cuisine, count(*)::int AS n
            FROM hearth.recipe_swipes s
            JOIN hearth.public_recipes pr ON pr.id = s.public_recipe_id
            WHERE s.household_id = $1::uuid AND s.direction = 'like'
            GROUP BY cuisine
            HAVING count(*) >= $2
            """,
            household_id, PROFILE_LEARN_THRESHOLD,
        )
    if not rows:
        return []

    profile = await load_profile(household_id)
    existing = {c.lower() for c in profile.cuisines}
    additions = [r["cuisine"] for r in rows if r["cuisine"] and r["cuisine"].lower() not in existing]
    if not additions:
        return []

    profile.cuisines = list(profile.cuisines) + additions
    await _save_profile(household_id, profile)
    log.info("[explore] household=%s added cuisines: %s", household_id, additions)
    return additions
