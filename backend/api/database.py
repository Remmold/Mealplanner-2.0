import os
from contextlib import contextmanager
from pathlib import Path

import duckdb
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DUCKDB_PATH = Path(__file__).resolve().parent.parent / os.getenv("DUCKDB_PATH", "food_data.duckdb")


@contextmanager
def get_connection():
    """Yield a read-only DuckDB connection, then close it."""
    conn = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        yield conn
    finally:
        conn.close()
