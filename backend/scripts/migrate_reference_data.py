"""One-shot copy of the reference catalog (USDA + curated pantry + aliases +
units) from DuckDB / SQLite into Postgres.

Idempotent — re-runnable safely thanks to ON CONFLICT DO NOTHING on every
INSERT. Use this whenever the local catalog changes and you want to push the
update to Supabase.

Run from backend/:
    uv run python -m scripts.migrate_reference_data
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
from pathlib import Path

import asyncpg
import duckdb
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")


DATABASE_URL = os.environ.get("DATABASE_URL", "")
DUCKDB_PATH = ROOT / os.environ.get("DUCKDB_PATH", "food_data.duckdb")
SQLITE_PATH = ROOT / "recipes.db"

BATCH = 500


async def copy_usda(pg: asyncpg.Connection, duck: duckdb.DuckDBPyConnection) -> None:
    print("[USDA] reading from DuckDB...")
    rows = duck.execute(
        """
        SELECT
            fdc_id,
            name,
            food_group,
            energy_kcal_100g,
            proteins_100g,
            fat_100g,
            carbohydrates_100g,
            fiber_100g,
            sugars_100g,
            saturated_fat_100g,
            salt_100g
        FROM usda.ingredients
        """
    ).fetchall()
    print(f"[USDA] {len(rows)} rows to insert")

    records = [
        (
            r[0],   # fdc_id
            r[1],   # description (name in DuckDB)
            r[2],   # food_group
            r[3],   # energy_kcal
            r[4],   # protein_g
            r[5],   # fat_g
            r[6],   # carbs_g
            r[7],   # fiber_g
            r[8],   # sugar_g
            r[9],   # saturated_fat_g
            r[10],  # salt_g
        )
        for r in rows
    ]

    inserted = 0
    for i in range(0, len(records), BATCH):
        chunk = records[i:i + BATCH]
        await pg.executemany(
            """
            INSERT INTO hearth.usda_ingredients
                (fdc_id, description, food_group,
                 energy_kcal, protein_g, fat_g, carbs_g, fiber_g, sugar_g,
                 saturated_fat_g, salt_g)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (fdc_id) DO NOTHING
            """,
            chunk,
        )
        inserted += len(chunk)
        if inserted % 2000 == 0 or inserted == len(records):
            print(f"[USDA] {inserted}/{len(records)}")
    print("[USDA] done.")


async def copy_pantry(
    pg: asyncpg.Connection,
    duck: duckdb.DuckDBPyConnection,
    sqlite_conn: sqlite3.Connection,
) -> None:
    """Union of dbt seed common_ingredients + SQLite pantry_ingredients.
    SQLite wins on fdc_id conflict (matches the runtime UNION behaviour)."""
    print("[PANTRY] reading dbt seed (DuckDB) and pantry (SQLite)...")
    seed_rows = duck.execute(
        "SELECT fdc_id, simple_name, category, subcategory FROM main.common_ingredients"
    ).fetchall()
    sqlite_rows = sqlite_conn.execute(
        "SELECT fdc_id, simple_name, category, subcategory FROM pantry_ingredients"
    ).fetchall()
    print(f"[PANTRY] dbt seed: {len(seed_rows)}, sqlite pantry: {len(sqlite_rows)}")

    union: dict[int, tuple] = {}
    for r in seed_rows:
        union[r[0]] = (r[0], r[1], r[2], r[3])
    for r in sqlite_rows:
        union[r["fdc_id"]] = (
            r["fdc_id"], r["simple_name"], r["category"], r["subcategory"],
        )

    records = list(union.values())
    print(f"[PANTRY] {len(records)} unique fdc_ids to insert")

    for i in range(0, len(records), BATCH):
        chunk = records[i:i + BATCH]
        await pg.executemany(
            """
            INSERT INTO hearth.pantry_ingredients
                (fdc_id, simple_name, category, subcategory)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (fdc_id) DO NOTHING
            """,
            chunk,
        )
    print("[PANTRY] done.")


async def copy_aliases(pg: asyncpg.Connection, sqlite_conn: sqlite3.Connection) -> None:
    rows = sqlite_conn.execute(
        "SELECT alias_fdc_id, canonical_fdc_id FROM ingredient_aliases"
    ).fetchall()
    print(f"[ALIASES] {len(rows)} rows")
    if not rows:
        return
    records = [(r["alias_fdc_id"], r["canonical_fdc_id"]) for r in rows]
    await pg.executemany(
        """
        INSERT INTO hearth.ingredient_aliases (alias_fdc_id, canonical_fdc_id)
        VALUES ($1, $2)
        ON CONFLICT (alias_fdc_id) DO NOTHING
        """,
        records,
    )
    print("[ALIASES] done.")


async def copy_units(pg: asyncpg.Connection, sqlite_conn: sqlite3.Connection) -> None:
    rows = sqlite_conn.execute(
        "SELECT fdc_id, display_unit, grams_per_unit, round_step FROM ingredient_units"
    ).fetchall()
    print(f"[UNITS] {len(rows)} rows")
    if not rows:
        return
    records = [
        (r["fdc_id"], r["display_unit"], r["grams_per_unit"], r["round_step"])
        for r in rows
    ]
    await pg.executemany(
        """
        INSERT INTO hearth.ingredient_units
            (fdc_id, display_unit, grams_per_unit, round_step)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (fdc_id) DO NOTHING
        """,
        records,
    )
    print("[UNITS] done.")


async def main() -> None:
    if not DATABASE_URL:
        print("DATABASE_URL not configured in backend/.env", file=sys.stderr)
        sys.exit(1)
    if not DUCKDB_PATH.exists():
        print(f"DuckDB file not found: {DUCKDB_PATH}", file=sys.stderr)
        sys.exit(1)
    if not SQLITE_PATH.exists():
        print(f"SQLite file not found: {SQLITE_PATH}", file=sys.stderr)
        sys.exit(1)

    print(f"Source DuckDB: {DUCKDB_PATH}")
    print(f"Source SQLite: {SQLITE_PATH}")
    print(f"Target Postgres: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else '...'}")
    print()

    duck = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    sqlite_conn = sqlite3.connect(str(SQLITE_PATH))
    sqlite_conn.row_factory = sqlite3.Row
    pg = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
    try:
        await copy_usda(pg, duck)
        await copy_pantry(pg, duck, sqlite_conn)
        await copy_aliases(pg, sqlite_conn)
        await copy_units(pg, sqlite_conn)
        print("\nAll done.")
    finally:
        await pg.close()
        duck.close()
        sqlite_conn.close()


if __name__ == "__main__":
    asyncio.run(main())
