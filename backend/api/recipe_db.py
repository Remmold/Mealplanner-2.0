"""SQLite database for recipe persistence (Supabase-ready schema)."""

import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "recipes.db"

DEFAULT_HOUSEHOLD_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_HOUSEHOLD_NAME = "My Household"


def new_id() -> str:
    return str(uuid.uuid4())


@contextmanager
def get_recipe_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create tables if they don't exist and ensure default household."""
    with get_recipe_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS households (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS recipes (
                id TEXT PRIMARY KEY,
                household_id TEXT NOT NULL REFERENCES households(id),
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS recipe_ingredients (
                id TEXT PRIMARY KEY,
                recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                fdc_id INTEGER NOT NULL,
                quantity_g REAL NOT NULL,
                UNIQUE(recipe_id, fdc_id)
            );

            CREATE INDEX IF NOT EXISTS idx_recipes_household
                ON recipes(household_id);

            CREATE INDEX IF NOT EXISTS idx_recipe_ingredients_recipe
                ON recipe_ingredients(recipe_id);
        """)

        # Ensure default household exists
        existing = conn.execute(
            "SELECT id FROM households WHERE id = ?", [DEFAULT_HOUSEHOLD_ID]
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO households (id, name) VALUES (?, ?)",
                [DEFAULT_HOUSEHOLD_ID, DEFAULT_HOUSEHOLD_NAME],
            )


# Initialize on import
init_db()
