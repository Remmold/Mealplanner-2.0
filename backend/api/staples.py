"""Household staples — the per-household 'always have at home' fdc_id set.

Drives:
  * shopping-list split (omit staples from the buy list, surface them in a
    'Check pantry' section)
  * recipe view split ('To buy' vs 'From pantry')
  * comfort threshold (count of non-staple ingredients)

Auto-seed: the first time a household calls GET /staples, we resolve the
applicable entries from system_staples.SYSTEM_STAPLES (filtered by
profile.cuisines) against the global usda_ingredients catalogue and seed
the household_staples table. After that the user owns the list.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import CurrentUser, get_current_user
from api.db import get_current_household_id, service_tx, user_tx
from api.profile import load_profile
from api.system_staples import SYSTEM_STAPLES, applicable_to

log = logging.getLogger("staples")

router = APIRouter(prefix="/staples", tags=["staples"])


class StapleEntry(BaseModel):
    fdc_id: int
    name: str
    category: str


class StaplesPayload(BaseModel):
    items: list[StapleEntry]
    seeded_now: bool = False


# ---------------------------------------------------------------------------
# Auto-seed helpers
# ---------------------------------------------------------------------------


async def _resolve_simple_name(conn, simple_name: str) -> int | None:
    """Look up a curated-catalogue entry by exact simple_name. The curated
    catalogue is authoritative for staples — we never fall back to USDA's
    raw descriptions because those look like 'Spices, salt, table'."""
    row = await conn.fetchrow(
        "SELECT fdc_id FROM hearth.pantry_ingredients "
        "WHERE lower(simple_name) = lower($1) LIMIT 1",
        simple_name,
    )
    return int(row["fdc_id"]) if row else None


async def seed_household_if_empty(household_id: str) -> int:
    """If the household has no staples, populate from the system list
    filtered by their profile.cuisines. Returns the number of items
    inserted (0 if the household already had any)."""
    profile = await load_profile(household_id)

    async with service_tx() as conn:
        existing = await conn.fetchval(
            "SELECT count(*) FROM hearth.household_staples WHERE household_id = $1::uuid",
            household_id,
        )
        if existing and int(existing) > 0:
            return 0

        applicable = applicable_to(profile.cuisines)
        inserted = 0
        unresolved: list[str] = []
        for staple in applicable:
            fdc_id = await _resolve_simple_name(conn, staple["simple_name"])
            if fdc_id is None:
                unresolved.append(staple["simple_name"])
                continue
            res = await conn.execute(
                """
                INSERT INTO hearth.household_staples (household_id, fdc_id)
                VALUES ($1::uuid, $2)
                ON CONFLICT DO NOTHING
                """,
                household_id, fdc_id,
            )
            if "INSERT 0 1" in res:
                inserted += 1
        if unresolved:
            log.warning(
                "[staples] %d simple_names not in curated catalogue (skipped): %s",
                len(unresolved), unresolved,
            )
        log.info("[staples] seeded household=%s with %d staples", household_id, inserted)
        return inserted


# ---------------------------------------------------------------------------
# Public helpers (used elsewhere)
# ---------------------------------------------------------------------------


# Reverse lookup: simple_name -> category (used to group the UI by kitchen
# category, not USDA food group).
_NAME_TO_CATEGORY: dict[str, str] = {
    s["simple_name"].lower(): s["category"] for s in SYSTEM_STAPLES
}


def category_for_simple_name(simple_name: str) -> str:
    return _NAME_TO_CATEGORY.get(simple_name.lower(), "Other")


async def list_staple_fdc_ids(household_id: str) -> set[int]:
    """Set of fdc_ids that count as 'in the pantry' for this household.
    Used by shopping-list + recipe-view to split ingredients."""
    async with service_tx() as conn:
        rows = await conn.fetch(
            "SELECT fdc_id FROM hearth.household_staples WHERE household_id = $1::uuid",
            household_id,
        )
    return {int(r["fdc_id"]) for r in rows}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=StaplesPayload)
async def list_staples(
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    """List the household's pantry staples. On the very first call, also
    seed the household from the system list (filtered by profile.cuisines)."""
    seeded_now_count = await seed_household_if_empty(household_id)
    async with user_tx(user) as conn:
        # Prefer the curated simple_name when the fdc_id is in our pantry
        # catalogue; otherwise fall back to USDA's description so a hand-
        # added obscure fdc_id still has SOMETHING to render.
        rows = await conn.fetch(
            """
            SELECT hs.fdc_id,
                   COALESCE(p.simple_name, u.description) AS name
            FROM hearth.household_staples hs
            LEFT JOIN hearth.pantry_ingredients p ON p.fdc_id = hs.fdc_id
            LEFT JOIN hearth.usda_ingredients   u ON u.fdc_id = hs.fdc_id
            WHERE hs.household_id = $1::uuid
            ORDER BY name
            """,
            household_id,
        )

    items: list[StapleEntry] = [
        StapleEntry(
            fdc_id=int(r["fdc_id"]),
            name=str(r["name"]),
            category=category_for_simple_name(str(r["name"])),
        )
        for r in rows
    ]
    return StaplesPayload(items=items, seeded_now=seeded_now_count > 0)


class StapleIn(BaseModel):
    fdc_id: int


@router.post("", status_code=201)
async def add_staple(
    body: StapleIn,
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    async with user_tx(user) as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM hearth.usda_ingredients WHERE fdc_id = $1",
            body.fdc_id,
        )
        if not exists:
            raise HTTPException(404, "fdc_id not in USDA catalogue")
        await conn.execute(
            """
            INSERT INTO hearth.household_staples (household_id, fdc_id)
            VALUES ($1::uuid, $2)
            ON CONFLICT DO NOTHING
            """,
            household_id, body.fdc_id,
        )
    return {"ok": True}


@router.delete("/{fdc_id}", status_code=204)
async def remove_staple(
    fdc_id: int,
    user: CurrentUser = Depends(get_current_user),
    household_id: str = Depends(get_current_household_id),
):
    async with user_tx(user) as conn:
        await conn.execute(
            "DELETE FROM hearth.household_staples "
            "WHERE household_id = $1::uuid AND fdc_id = $2",
            household_id, fdc_id,
        )
