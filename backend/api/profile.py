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

from fastapi import APIRouter, Depends
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
    "visible_slots": "Which meal slots the household plans on the calendar. "
        "Subset of ['breakfast','lunch','dinner']. If the user says e.g. "
        "\"we generally don't want our breakfasts planned\", set this to "
        "['lunch','dinner']. Empty list / unset = all three slots shown.",
    "max_ingredients_to_buy": "Comfort threshold — how many NON-staple "
        "ingredients the household is comfortable shopping for per recipe. "
        "Default 8. Used to rank recipes (over-threshold sinks in Explore + "
        "the meal-plan generator avoids them); not a hard filter.",
}

LIST_FIELDS = {"dietary", "allergies", "dislikes", "likes", "cuisines", "kitchen_equipment", "visible_slots"}
# Additive list fields ACCUMULATE: "we also dislike X" should append to the
# existing list, not replace it. visible_slots is deliberately NOT additive — it
# is a full set ("we plan lunch and dinner"), so it always replaces.
ADDITIVE_LIST_FIELDS = LIST_FIELDS - {"visible_slots"}
VALID_SLOTS: set[str] = {"breakfast", "lunch", "dinner"}
INT_FIELDS = {"family_size", "typical_cook_time_min", "max_ingredients_to_buy"}
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
        cleaned = [str(s).strip().lower() for s in items if str(s).strip()]
        if field == "visible_slots":
            invalid = [s for s in cleaned if s not in VALID_SLOTS]
            if invalid:
                raise ValueError(
                    f"visible_slots must contain only 'breakfast', 'lunch', 'dinner' "
                    f"(got {invalid!r})."
                )
        return cleaned
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


def apply_field_mode(field: str, existing: Any, incoming: list, mode: str) -> list:
    """Combine an incoming list-field value with what's already stored.

    Additive list fields default to 'add' (union, order-preserving, deduped) so a
    statement like "we also dislike spicy food" appends rather than clobbering the
    existing dislikes. 'remove' drops the incoming items; 'set' replaces wholesale.
    Non-additive fields (visible_slots) always replace and never reach the merge."""
    if field not in ADDITIVE_LIST_FIELDS:
        return incoming
    base = list(existing) if isinstance(existing, list) else []
    if mode == "set":
        return incoming
    if mode == "remove":
        drop = set(incoming)
        return [x for x in base if x not in drop]
    merged = list(base)                       # 'add' (default)
    for x in incoming:
        if x not in merged:
            merged.append(x)
    return merged


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
    visible_slots: list[str] = Field(default_factory=list)
    max_ingredients_to_buy: int | None = None
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


# ------------------------------------------------------------------
# Plain-language descriptions of a profile change.
#
# The human-in-the-loop cards (and their post-accept confirmation) used to show
# the raw shape — "Add ['lök'] to profile.dislikes" — which reads like a
# database dump. These helpers turn a (field, value, mode) into a sentence an
# everyday user understands. Used by the proposal summary (agent_core.tools) and
# the executor result (pending_actions) so both stay in sync.
# ------------------------------------------------------------------

FIELD_LABELS: dict[str, str] = {
    "family_size": "household size",
    "dietary": "dietary needs",
    "allergies": "allergies",
    "dislikes": "disliked ingredients",
    "likes": "favourites",
    "cuisines": "favourite cuisines",
    "kitchen_equipment": "kitchen equipment",
    "visible_slots": "planned meals",
    "typical_cook_time_min": "usual cooking time",
    "batch_cook_preference": "batch-cooking preference",
    "budget_level": "budget level",
    "max_ingredients_to_buy": "shopping-list comfort level",
}

FIELD_LABELS_SV: dict[str, str] = {
    "family_size": "hushållsstorlek",
    "dietary": "kostbehov",
    "allergies": "allergier",
    "dislikes": "ogillade ingredienser",
    "likes": "favoriter",
    "cuisines": "favoritkök",
    "kitchen_equipment": "köksutrustning",
    "visible_slots": "planerade måltider",
    "typical_cook_time_min": "vanliga tillagningstid",
    "batch_cook_preference": "inställning för satskokning",
    "budget_level": "budgetnivå",
    "max_ingredients_to_buy": "komfortnivå för inköpslista",
}

# Slot enum values are stored in English; translate for display only.
_SLOT_SV: dict[str, str] = {"breakfast": "frukost", "lunch": "lunch", "dinner": "middag"}


def _is_sv(locale: str | None) -> bool:
    return (locale or "").lower().startswith("sv")


def _field_label(field: str, locale: str = "en") -> str:
    table = FIELD_LABELS_SV if _is_sv(locale) else FIELD_LABELS
    return table.get(field, field.replace("_", " "))


def human_list(items: Any, locale: str = "en") -> str:
    """Join a list into prose: [] -> '', [a] -> 'a', [a,b] -> 'a and b',
    [a,b,c] -> 'a, b and c' (Swedish uses 'och')."""
    vals = [str(x).strip() for x in items if str(x).strip()] if isinstance(items, list) else (
        [str(items).strip()] if str(items).strip() else []
    )
    if not vals:
        return ""
    if len(vals) == 1:
        return vals[0]
    conj = "och" if _is_sv(locale) else "and"
    return ", ".join(vals[:-1]) + f" {conj} " + vals[-1]


def describe_profile_value(field: str, value: Any, locale: str = "en") -> str:
    """Readable rendering of a coerced field value, with units where it helps."""
    sv = _is_sv(locale)
    if field == "visible_slots":
        slots = value if isinstance(value, list) else [value]
        if sv:
            slots = [_SLOT_SV.get(str(s), str(s)) for s in slots]
        return human_list(slots, locale) or ("alla måltider" if sv else "all meals")
    if field in LIST_FIELDS:
        return human_list(value, locale)
    if field == "typical_cook_time_min":
        return f"{value} minuter" if sv else f"{value} minutes"
    if field == "family_size":
        plural = "personer" if sv else "people"
        return f"{value} person" if str(value) == "1" else f"{value} {plural}"
    return str(value)


def describe_profile_change(field: str, value: Any, mode: str, locale: str = "en") -> str:
    """One sentence describing a PROPOSED change, for the Accept/Reject card."""
    sv = _is_sv(locale)
    label = _field_label(field, locale)
    rendered = describe_profile_value(field, value, locale)
    if field in ADDITIVE_LIST_FIELDS:
        if mode == "remove":
            return (f"Ta bort {rendered} från listan över {label}." if sv
                    else f"Remove {rendered} from your {label}.")
        if mode == "set":
            return (f"Ersätt listan över {label} med {rendered}." if sv
                    else f"Replace your {label} with {rendered}.")
        return (f"Lägg till {rendered} i listan över {label} (dina befintliga finns kvar)." if sv
                else f"Add {rendered} to your {label} (your existing ones stay).")
    if field == "visible_slots":
        return (f"Planera bara dessa måltider i kalendern: {rendered}." if sv
                else f"Plan only these meals on your calendar: {rendered}.")
    return (f"Ändra din {label} till {rendered}." if sv
            else f"Set your {label} to {rendered}.")


def describe_profile_result(field: str, new_value: Any, locale: str = "en") -> str:
    """One sentence confirming the APPLIED state, shown after Accept."""
    sv = _is_sv(locale)
    label = _field_label(field, locale)
    rendered = describe_profile_value(field, new_value, locale)
    if field == "visible_slots":
        return (f"Du ser nu {rendered} i kalendern." if sv
                else f"You'll now see {rendered} on your calendar.")
    if field in LIST_FIELDS:
        if sv:
            return f"Listan över {label} är nu: {rendered}." if rendered else f"Listan över {label} är nu tom."
        return f"Your {label} are now: {rendered}." if rendered else f"Your {label} are now empty."
    return (f"Din {label} är nu {rendered}." if sv else f"Your {label} is now {rendered}.")


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
