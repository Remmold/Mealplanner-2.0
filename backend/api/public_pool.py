"""Shared helpers for the public recipe pool.

The pool (`hearth.public_recipes`) is the source of truth for everything the
Explore deck shows: starter corpus, LLM-generated recipes from any household,
and (later) household-opted shares. Per-household personal copies live in
`hearth.recipes` and may carry a `public_origin_id` pointer back here.

This module exposes:
  * mirror_to_pool(...)      — called after a successful LLM recipe gen
  * copy_to_household(...)   — used by Explore's like-swipe and starter import
  * pool_recipe_by_id(...)   — small fetch helper
"""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

from api.db import service_tx
from api.image_gen import schedule_image

log = logging.getLogger("public_pool")


async def mirror_to_pool(
    name: str,
    ingredients: list[dict],   # [{fdc_id, name, quantity_g}, ...]
    instructions: list[str],
    *,
    source: str,                # 'llm' | 'household_share'
    originating_household_id: str | None,
    meal_type: str | None = None,
    cuisine: list[str] | None = None,
    dietary: list[str] | None = None,
    time_min: int | None = None,
) -> str | None:
    """Insert a copy into the public pool. Returns the new public_recipes.id,
    or None if the name already exists (the user's chosen dedup policy).
    Safe to call inside an open transaction's lifetime — uses its own
    service_tx so a rollback of the LLM caller doesn't cascade here.

    Eligibility check: components / desserts / drinks are saved to the
    household's personal recipes but NOT mirrored to the shared dinner
    deck. Same rules the amcoff backfill applies."""
    from api.pool_filters import pool_rejection_reason

    rejection = pool_rejection_reason(name, [])
    if rejection is not None:
        log.info(
            "[public_pool] skipping mirror of %r — classified as %s",
            name[:80], rejection,
        )
        return None

    payload_ings = [
        {"fdc_id": int(i["fdc_id"]), "name": i.get("name"), "quantity_g": float(i["quantity_g"])}
        for i in ingredients
    ]
    try:
        async with service_tx() as conn:
            # Pass Python objects directly — the connection's jsonb codec
            # encodes them. Calling json.dumps here would double-encode and
            # the column would end up holding a JSON STRING instead of an
            # array/object.
            row = await conn.fetchrow(
                """
                INSERT INTO hearth.public_recipes
                    (name, ingredients, instructions, meal_type, cuisine,
                     dietary, time_min, source, originating_household_id)
                VALUES ($1, $2::jsonb, $3::jsonb, $4, $5::text[], $6::text[], $7, $8, $9::uuid)
                ON CONFLICT ((lower(name))) DO NOTHING
                RETURNING id::text AS id
                """,
                name,
                payload_ings,
                instructions,
                meal_type,
                cuisine or [],
                dietary or [],
                time_min,
                source,
                originating_household_id,
            )
            return row["id"] if row else None
    except Exception:
        # Don't let pool failures break the upstream save.
        log.exception("[public_pool] mirror failed for %r", name[:80])
        return None


async def pool_recipe_by_id(conn: asyncpg.Connection, public_recipe_id: str) -> dict | None:
    row = await conn.fetchrow(
        """
        SELECT id::text AS id, name, ingredients, instructions, meal_type,
               cuisine, dietary, time_min, source, image_path
        FROM hearth.public_recipes
        WHERE id = $1::uuid
        """,
        public_recipe_id,
    )
    if not row:
        return None
    return _row_to_dict(row)


def _row_to_dict(row: asyncpg.Record) -> dict:
    """Normalise a public_recipes row into a JSON-shaped dict.
    jsonb columns come back as Python lists/dicts already; text[] as lists."""
    return {
        "id":           row["id"] if isinstance(row["id"], str) else str(row["id"]),
        "name":         row["name"],
        "ingredients":  list(row["ingredients"]) if row["ingredients"] else [],
        "instructions": list(row["instructions"]) if row["instructions"] else [],
        "meal_type":    row["meal_type"],
        "cuisine":      list(row["cuisine"] or []),
        "dietary":      list(row["dietary"] or []),
        "time_min":     row["time_min"],
        "source":       row["source"],
        "image_path":   row["image_path"],
    }


async def copy_to_household(
    public_recipe_id: str,
    household_id: str,
    *,
    schedule_image_gen: bool = True,
) -> tuple[str | None, str | None]:
    """Insert a per-household copy of the given pool recipe. Returns
    (recipe_id, name). If the household already imported this pool recipe
    (by public_origin_id), returns the existing recipe_id without inserting."""
    async with service_tx() as conn:
        pool = await pool_recipe_by_id(conn, public_recipe_id)
        if pool is None:
            return None, None

        existing = await conn.fetchval(
            "SELECT id::text FROM hearth.recipes "
            "WHERE household_id = $1::uuid AND public_origin_id = $2::uuid",
            household_id, public_recipe_id,
        )
        if existing:
            return existing, pool["name"]

        # Same name already in household but not from explore — block import.
        name_clash = await conn.fetchval(
            "SELECT id::text FROM hearth.recipes "
            "WHERE household_id = $1::uuid AND lower(name) = lower($2)",
            household_id, pool["name"],
        )
        if name_clash:
            return name_clash, pool["name"]

        recipe_row = await conn.fetchrow(
            """
            INSERT INTO hearth.recipes
                (household_id, name, instructions, servings, meal_type,
                 image_path, public_origin_id)
            VALUES ($1::uuid, $2, $3::jsonb, $4, $5, $6, $7::uuid)
            RETURNING id::text AS id
            """,
            household_id,
            pool["name"],
            pool["instructions"],   # codec encodes; passing json.dumps doubles up
            4,
            pool["meal_type"],
            pool["image_path"],
            public_recipe_id,
        )
        rid = recipe_row["id"]

        # Dedup by fdc_id; then drop any LLM-hallucinated codes that aren't
        # in usda_ingredients. The FK would reject them otherwise and abort
        # the whole import, leaving the user with no recipe at all.
        grams_by_fdc: dict[int, float] = {}
        for ing in pool["ingredients"]:
            fid = int(ing["fdc_id"])
            grams_by_fdc[fid] = grams_by_fdc.get(fid, 0.0) + float(ing["quantity_g"])
        if grams_by_fdc:
            valid_rows = await conn.fetch(
                "SELECT fdc_id FROM hearth.usda_ingredients "
                "WHERE fdc_id = ANY($1::int[])",
                list(grams_by_fdc.keys()),
            )
            valid_set = {r["fdc_id"] for r in valid_rows}
            dropped = [fid for fid in grams_by_fdc if fid not in valid_set]
            if dropped:
                log.warning(
                    "[public_pool] skipping invalid fdc_ids on import of %r: %s",
                    pool["name"], dropped,
                )
            for fdc_id, qty in grams_by_fdc.items():
                if fdc_id not in valid_set:
                    continue
                await conn.execute(
                    "INSERT INTO hearth.recipe_ingredients (recipe_id, fdc_id, quantity_g) "
                    "VALUES ($1::uuid, $2, $3)",
                    rid, fdc_id, qty,
                )

        if schedule_image_gen and not pool["image_path"]:
            try:
                schedule_image(rid, pool["name"], household_id)
            except Exception:
                pass  # image gen is best-effort; pollinations.ai is 402'ing anyway

        return rid, pool["name"]
