"""Household profile — structured + free-form context that the assistant uses
to personalise recipes and meal plans.

Storage: `hearth.household_profiles` (one row per household, `data` is JSONB).
asyncpg's jsonb codec (registered in db.py) auto-encodes/decodes Python dicts,
so we just hand it `profile.model_dump()` on write and receive a dict on read.

Reads use `service_tx` because the helpers (load_profile, _save_profile) are
called from non-handler code (chat agent tools, meal-plan generator, pending
action executors) where we don't have a CurrentUser to thread through. Service
role bypasses RLS; safety comes from the caller passing a household_id that
came from `get_current_household_id` (which itself validates membership).
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.db import get_current_household_id, service_tx

router = APIRouter(prefix="/profile", tags=["profile"])


# ============================================================
# Shape
# ============================================================

PROFILE_FIELDS: dict[str, str] = {
    "family_size": "How many people the household regularly cooks for.",
    "dietary": "List of dietary modes: 'vegetarian', 'vegan', 'pescatarian', 'gluten-free', 'dairy-free', etc.",
    "allergies": "List of allergies (strict avoidances). Never include these in recipes.",
    "dislikes": "List of ingredients/dishes the household prefers to avoid (not strict).",
    "likes": "List of favourite ingredients, cuisines, or dishes.",
    "typical_cook_time_min": "Typical weekday cook-time tolerance in minutes (e.g. 30).",
    "batch_cook_preference": "'none' | 'moderate' | 'heavy' — how much they want to batch-cook.",
    "kitchen_equipment": "List: 'oven', 'stove', 'slow cooker', 'pressure cooker', 'grill', 'wok', 'blender', ...",
    "cuisines": "Preferred cuisines in rough priority order.",
    "budget_level": "'thrifty' | 'moderate' | 'splurge'.",
}

LIST_FIELDS = {"dietary", "allergies", "dislikes", "likes", "cuisines", "kitchen_equipment"}
INT_FIELDS = {"family_size", "typical_cook_time_min"}
ENUM_FIELDS: dict[str, set[str]] = {
    "batch_cook_preference": {"none", "moderate", "heavy"},
    "budget_level": {"thrifty", "moderate", "splurge"},
}


def coerce_profile_value(field: str, value: Any) -> Any:
    """Coerce a raw field value to the type the profile expects.

    Raises ValueError with a user-facing message when the value can't be
    represented — e.g. a qualitative word ('easy') for an integer field. Callers
    surface that message to the agent so it self-corrects instead of queueing a
    proposal that would later fail on accept.
    """
    if field not in PROFILE_FIELDS:
        raise ValueError(f"Unknown field '{field}'. Valid: {', '.join(PROFILE_FIELDS)}")
    if field in LIST_FIELDS:
        items = value if isinstance(value, list) else str(value).split(",")
        return [str(s).strip() for s in items if str(s).strip()]
    if field in INT_FIELDS:
        s = str(value).strip()
        try:
            return int(s)
        except (ValueError, TypeError):
            m = re.search(r"\d+", s)
            if m:
                return int(m.group())
            unit = " of minutes" if field == "typical_cook_time_min" else ""
            raise ValueError(
                f"{field} must be a whole number{unit} (got {value!r}). If the user only "
                f"described it qualitatively, record a note or ask for a concrete number instead."
            )
    if field in ENUM_FIELDS:
        v = str(value).strip().lower()
        if v not in ENUM_FIELDS[field]:
            raise ValueError(f"{field} must be one of {sorted(ENUM_FIELDS[field])} (got {value!r}).")
        return v
    return str(value).strip()


class HouseholdProfile(BaseModel):
    family_size: int | None = None
    dietary: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)
    likes: list[str] = Field(default_factory=list)
    typical_cook_time_min: int | None = None
    batch_cook_preference: str | None = None
    kitchen_equipment: list[str] = Field(default_factory=list)
    cuisines: list[str] = Field(default_factory=list)
    budget_level: str | None = None
    notes: list[str] = Field(default_factory=list)
    updated_at: str | None = None


# ============================================================
# Helpers (used by chat.py, meal_plans.py, agent_tools.py, pending_actions.py)
# ============================================================


async def load_profile(household_id: str) -> HouseholdProfile:
    async with service_tx() as conn:
        row = await conn.fetchrow(
            "SELECT data, updated_at FROM hearth.household_profiles "
            "WHERE household_id = $1::uuid",
            household_id,
        )
    if row is None:
        return HouseholdProfile()
    data = dict(row["data"]) if row["data"] else {}
    if row["updated_at"] is not None:
        data["updated_at"] = row["updated_at"].isoformat()
    try:
        return HouseholdProfile(**data)
    except Exception:
        # Schema drift safety net.
        return HouseholdProfile(notes=data.get("notes", []) or [])


async def _save_profile(household_id: str, profile: HouseholdProfile) -> HouseholdProfile:
    payload = profile.model_dump(exclude={"updated_at"})
    async with service_tx() as conn:
        await conn.execute(
            """
            INSERT INTO hearth.household_profiles (household_id, data)
            VALUES ($1::uuid, $2::jsonb)
            ON CONFLICT (household_id) DO UPDATE SET
                data = excluded.data,
                updated_at = now()
            """,
            household_id, payload,
        )
    return await load_profile(household_id)


def render_profile_context(profile: HouseholdProfile, max_notes: int = 20) -> str:
    """Format the profile as a human-readable block for LLM system/user prompts."""
    lines: list[str] = []
    if profile.family_size:
        lines.append(f"- Family size: {profile.family_size}")
    if profile.dietary:
        lines.append(f"- Dietary: {', '.join(profile.dietary)}")
    if profile.allergies:
        lines.append(f"- ALLERGIES (strict avoid): {', '.join(profile.allergies)}")
    if profile.dislikes:
        lines.append(f"- Dislikes: {', '.join(profile.dislikes)}")
    if profile.likes:
        lines.append(f"- Likes: {', '.join(profile.likes)}")
    if profile.cuisines:
        lines.append(f"- Preferred cuisines: {', '.join(profile.cuisines)}")
    if profile.typical_cook_time_min:
        lines.append(f"- Typical cook-time tolerance: {profile.typical_cook_time_min} min")
    if profile.batch_cook_preference:
        lines.append(f"- Batch-cook preference: {profile.batch_cook_preference}")
    if profile.kitchen_equipment:
        lines.append(f"- Kitchen equipment: {', '.join(profile.kitchen_equipment)}")
    if profile.budget_level:
        lines.append(f"- Budget level: {profile.budget_level}")
    if profile.notes:
        lines.append("- Observations from prior conversations:")
        for n in profile.notes[-max_notes:]:
            lines.append(f"  * {n}")
    if not lines:
        return "(no profile on file yet — you should ask a few discovery questions)"
    return "\n".join(lines)


def is_profile_sparse(profile: HouseholdProfile) -> bool:
    known = sum(
        1 for v in (
            profile.family_size, profile.dietary, profile.allergies,
            profile.dislikes, profile.likes, profile.typical_cook_time_min,
            profile.batch_cook_preference, profile.kitchen_equipment,
            profile.cuisines, profile.budget_level,
        )
        if v
    )
    return known < 3


# ============================================================
# Endpoints
# ============================================================


class ProfilePatch(BaseModel):
    """Partial update. Any field set replaces; append_notes adds to the tail."""
    family_size: int | None = None
    dietary: list[str] | None = None
    allergies: list[str] | None = None
    dislikes: list[str] | None = None
    likes: list[str] | None = None
    typical_cook_time_min: int | None = None
    batch_cook_preference: str | None = None
    kitchen_equipment: list[str] | None = None
    cuisines: list[str] | None = None
    budget_level: str | None = None
    notes: list[str] | None = None         # full replace
    append_notes: list[str] | None = None  # append


@router.get("", response_model=HouseholdProfile)
async def get_profile(household_id: str = Depends(get_current_household_id)):
    return await load_profile(household_id)


@router.patch("", response_model=HouseholdProfile)
async def patch_profile(
    body: ProfilePatch,
    household_id: str = Depends(get_current_household_id),
):
    current = await load_profile(household_id)
    data = current.model_dump(exclude={"updated_at"})

    updates: dict[str, Any] = body.model_dump(exclude_none=True)
    appended = updates.pop("append_notes", None)
    for k, v in updates.items():
        data[k] = v
    if appended:
        existing = list(data.get("notes", []))
        existing.extend(appended)
        data["notes"] = existing

    return await _save_profile(household_id, HouseholdProfile(**data))


@router.delete("", status_code=204)
async def reset_profile(household_id: str = Depends(get_current_household_id)):
    async with service_tx() as conn:
        await conn.execute(
            "DELETE FROM hearth.household_profiles WHERE household_id = $1::uuid",
            household_id,
        )
    return None
