"""
Entry point for the Open Food Facts ingestion pipeline.

Usage:
    # From backend/ directory:
    uv run python -m pipeline.run

Environment variables (see .env.example):
    OFF_DUMP_PATH      - path to local .jsonl.gz dump (downloaded if missing)
    OFF_CATEGORIES     - comma-separated OFF category tags (optional override)
    OFF_MAX_RECORDS    - stop after N matched records, 0 = no limit (default 0)
    DUCKDB_PATH        - local DuckDB file path (default: food_data.duckdb)
    DESTINATION        - "duckdb" (default) or "postgres"
    POSTGRES_CONNECTION_STRING - required when DESTINATION=postgres
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()


def _get_destination():
    import dlt

    dest = os.getenv("DESTINATION", "duckdb").lower()
    if dest == "postgres":
        conn_str = os.getenv("POSTGRES_CONNECTION_STRING")
        if not conn_str:
            print("ERROR: POSTGRES_CONNECTION_STRING must be set when DESTINATION=postgres")
            sys.exit(1)
        return dlt.destinations.postgres(conn_str)

    duckdb_path = os.getenv("DUCKDB_PATH", "food_data.duckdb")
    return dlt.destinations.duckdb(credentials=duckdb_path)


def _get_categories() -> list[str]:
    raw = os.getenv("OFF_CATEGORIES", "")
    if raw.strip():
        return [c.strip() for c in raw.split(",") if c.strip()]
    from pipeline.sources.open_food_facts import DEFAULT_CATEGORIES
    return DEFAULT_CATEGORIES


def run():
    import dlt
    from pipeline.sources.open_food_facts import open_food_facts_source

    dump_path = os.getenv("OFF_DUMP_PATH", "off_dump.jsonl.gz")
    categories = _get_categories()
    max_records = int(os.getenv("OFF_MAX_RECORDS", "0"))
    destination = _get_destination()

    print(f"Dump        : {dump_path}")
    print(f"Destination : {destination}")
    print(f"Categories  : {categories}")
    print(f"Max records : {max_records or 'unlimited'}")
    print()

    pipeline = dlt.pipeline(
        pipeline_name="open_food_facts",
        destination=destination,
        dataset_name="off",
    )

    source = open_food_facts_source(
        dump_path=dump_path,
        categories=categories,
        max_records=max_records,
    )

    load_info = pipeline.run(source)
    print(load_info)

    try:
        with pipeline.sql_client() as client:
            with client.execute_query("SELECT COUNT(*) FROM products") as cur:
                count = cur.fetchone()[0]
                print(f"\nTotal products in food_data.products: {count:,}")
    except Exception:
        pass


if __name__ == "__main__":
    run()
