"""Ingest backend/seeds/amcoff_pool_seed.json into hearth.public_recipes.

Idempotent on lower(name) — re-running upserts. Uses source='starter_corpus'
for now (the public_recipes.source check constraint only allows starter_corpus
/llm/household_share). A follow-up migration can add an 'amcoff_ica' source
value if we want to distinguish these in the UI later."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env")

SEED_PATH = BACKEND / "seeds" / "amcoff_pool_seed.json"


async def _init_conn(conn: asyncpg.Connection) -> None:
    # Same JSONB codec setup as the FastAPI pool — required so jsonb columns
    # round-trip as Python objects, not strings.
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


async def main() -> None:
    if not SEED_PATH.exists():
        raise SystemExit(
            f"Seed file not found: {SEED_PATH}\n"
            f"Run `python -m scripts.build_amcoff_pool_seed` first."
        )
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(seed)} amcoff records from {SEED_PATH.name}")

    conn = await asyncpg.connect(os.environ["DATABASE_URL"], statement_cache_size=0)
    await _init_conn(conn)
    try:
        inserted = 0
        updated = 0
        for r in seed:
            ingredients = [
                {
                    "fdc_id": int(i["fdc_id"]),
                    "name": i.get("name"),
                    "quantity_g": float(i["quantity_g"]),
                }
                for i in r["ingredients"]
            ]
            result = await conn.execute(
                """
                INSERT INTO hearth.public_recipes
                    (name, ingredients, instructions, meal_type, cuisine,
                     dietary, time_min, source)
                VALUES
                    ($1, $2::jsonb, $3::jsonb, $4, $5::text[], $6::text[], $7,
                     'starter_corpus')
                ON CONFLICT ((lower(name))) DO UPDATE SET
                    ingredients  = excluded.ingredients,
                    instructions = excluded.instructions,
                    meal_type    = excluded.meal_type,
                    cuisine      = excluded.cuisine,
                    dietary      = excluded.dietary,
                    time_min     = excluded.time_min
                """,
                r["name"],
                ingredients,
                r["instructions"],
                r.get("meal_type"),
                r.get("cuisine", []),
                r.get("dietary", []),
                r.get("time_min"),
            )
            if "INSERT 0 1" in result:
                inserted += 1
            else:
                updated += 1

        total = await conn.fetchval(
            "SELECT count(*) FROM hearth.public_recipes WHERE source = 'starter_corpus'"
        )
        print(f"Inserted {inserted}, updated {updated}.")
        print(f"Pool now has {total} starter recipes.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
