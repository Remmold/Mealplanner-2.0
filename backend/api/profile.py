"""Household profile — structured + free-form context that the assistant uses
to personalise recipes and meal plans.

Fields are intentionally loose (all optional) so the profile can grow via chat
without needing schema migrations. Structured fields are used for filtering
(e.g. `dietary=["vegetarian"]` hard-constrains recipes), while `notes` captures
things the assistant picks up over time ("they hate rice but love bulgur").
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.recipe_db import DEFAULT_HOUSEHOLD_ID, get_recipe_db

router = APIRouter(prefix="/profile", tags=["profile"])


# ============================================================
# Shape
# ============================================================

# Fields the assistant can read and update. All optional — a brand-new household
# starts empty and fills in over time.
#
# Keep keys stable: tools reference them by name. Add new ones freely, but don't
# rename existing ones without migrating `household_profiles.data` JSON blobs.

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
# Helpers (used by chat.py, meal_plans.py, agent_tools.py)
# ============================================================


def load_profile(household_id: str = DEFAULT_HOUSEHOLD_ID) -> HouseholdProfile:
    with get_recipe_db() as conn:
        row = conn.execute(
            "SELECT data, updated_at FROM household_profiles WHERE household_id = ?",
            [household_id],
        ).fetchone()
    if not row:
        return HouseholdProfile()
    try:
        data = json.loads(row["data"]) if row["data"] else {}
    except (json.JSONDecodeError, TypeError):
        data = {}
    data["updated_at"] = row["updated_at"]
    try:
        return HouseholdProfile(**data)
    except Exception:
        # If schema drifted, return an empty one rather than error out
        return HouseholdProfile(notes=data.get("notes", []))


def _save_profile(household_id: str, profile: HouseholdProfile) -> HouseholdProfile:
    payload = profile.model_dump(exclude={"updated_at"})
    with get_recipe_db() as conn:
        conn.execute(
            "INSERT INTO household_profiles (household_id, data) VALUES (?, ?) "
            "ON CONFLICT(household_id) DO UPDATE SET "
            "data = excluded.data, updated_at = CURRENT_TIMESTAMP",
            [household_id, json.dumps(payload)],
        )
    return load_profile(household_id)


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
    """True if we don't know much about the user — triggers discovery behaviour."""
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
def get_profile(household_id: str = DEFAULT_HOUSEHOLD_ID):
    return load_profile(household_id)


@router.patch("", response_model=HouseholdProfile)
def patch_profile(body: ProfilePatch, household_id: str = DEFAULT_HOUSEHOLD_ID):
    current = load_profile(household_id)
    data = current.model_dump(exclude={"updated_at"})

    updates: dict[str, Any] = body.model_dump(exclude_none=True)
    appended = updates.pop("append_notes", None)
    for k, v in updates.items():
        data[k] = v
    if appended:
        existing = list(data.get("notes", []))
        existing.extend(appended)
        data["notes"] = existing

    return _save_profile(household_id, HouseholdProfile(**data))


@router.delete("", status_code=204)
def reset_profile(household_id: str = DEFAULT_HOUSEHOLD_ID):
    with get_recipe_db() as conn:
        conn.execute("DELETE FROM household_profiles WHERE household_id = ?", [household_id])
    return None
