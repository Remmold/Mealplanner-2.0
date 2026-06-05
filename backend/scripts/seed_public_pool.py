"""Ingest backend/seeds/starter_recipes.json into hearth.public_recipes.

Run this once after the corpus build script produces the JSON. Idempotent
on lower(name) — re-running upserts. Inserts as `source = 'starter_corpus'`.

Usage (from backend/, venv activated):
    python -m scripts.seed_public_pool
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

CORPUS_PATH = Path(__file__).resolve().parent.parent / "seeds" / "starter_recipes.json"


async def main() -> None:
    if not CORPUS_PATH.exists():
        raise SystemExit(
            f"Corpus not found at {CORPUS_PATH}. "
            f"Run `python -m scripts.build_starter_corpus` first."
        )

    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(corpus)} corpus entries from {CORPUS_PATH.name}")

    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        inserted = 0
        skipped = 0
        for r in corpus:
            # Convert ingredients list into the JSONB shape we store. We keep
            # both the fdc_id and the display name so the deck card can render
            # without a join.
            ingredients = [
                {"fdc_id": i["fdc_id"], "name": i.get("name"), "quantity_g": i["quantity_g"]}
                for i in r["ingredients"]
            ]
            result = await conn.execute(
                """
                INSERT INTO hearth.public_recipes
                    (name, ingredients, instructions, meal_type, cuisine,
                     dietary, time_min, source)
                VALUES
                    ($1, $2::jsonb, $3::jsonb, $4, $5::text[], $6::text[], $7, 'starter_corpus')
                ON CONFLICT ((lower(name))) DO UPDATE SET
                    ingredients  = excluded.ingredients,
                    instructions = excluded.instructions,
                    meal_type    = excluded.meal_type,
                    cuisine      = excluded.cuisine,
                    dietary      = excluded.dietary,
                    time_min     = excluded.time_min
                """,
                r["name"],
                json.dumps(ingredients),
                json.dumps(r["instructions"]),
                r.get("slot"),
                r.get("cuisine", []),
                r.get("dietary", []),
                r.get("time_min"),
            )
            if "INSERT 0 1" in result:
                inserted += 1
            else:
                skipped += 1

        total = await conn.fetchval(
            "SELECT count(*) FROM hearth.public_recipes WHERE source = 'starter_corpus'"
        )
        print(f"Inserted {inserted}, upserted {skipped}. Pool now has {total} starter recipes.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
