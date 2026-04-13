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
                instructions TEXT NOT NULL DEFAULT '[]',
                servings INTEGER NOT NULL DEFAULT 4,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS ingredient_units (
                fdc_id INTEGER PRIMARY KEY,
                display_unit TEXT NOT NULL,
                grams_per_unit REAL NOT NULL,
                round_step REAL NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS store_layout (
                household_id TEXT NOT NULL REFERENCES households(id),
                category TEXT NOT NULL,
                sort_index INTEGER NOT NULL,
                PRIMARY KEY (household_id, category)
            );

            CREATE TABLE IF NOT EXISTS pantry_ingredients (
                fdc_id INTEGER PRIMARY KEY,
                simple_name TEXT NOT NULL,
                category TEXT NOT NULL,
                subcategory TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS meal_plans (
                id TEXT PRIMARY KEY,
                household_id TEXT NOT NULL REFERENCES households(id),
                name TEXT NOT NULL,
                start_date TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS meal_plan_entries (
                id TEXT PRIMARY KEY,
                meal_plan_id TEXT NOT NULL REFERENCES meal_plans(id) ON DELETE CASCADE,
                recipe_id TEXT NOT NULL REFERENCES recipes(id),
                plan_date TEXT NOT NULL,
                slot TEXT,
                portions REAL NOT NULL DEFAULT 1
            );

            CREATE INDEX IF NOT EXISTS idx_meal_plans_household ON meal_plans(household_id);
            CREATE INDEX IF NOT EXISTS idx_meal_plan_entries_plan ON meal_plan_entries(meal_plan_id);

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

        # Lightweight migrations: add missing columns
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(recipes)").fetchall()}
        if "instructions" not in cols:
            conn.execute("ALTER TABLE recipes ADD COLUMN instructions TEXT NOT NULL DEFAULT '[]'")
        if "servings" not in cols:
            conn.execute("ALTER TABLE recipes ADD COLUMN servings INTEGER NOT NULL DEFAULT 4")

        # Ensure default household exists
        existing = conn.execute(
            "SELECT id FROM households WHERE id = ?", [DEFAULT_HOUSEHOLD_ID]
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO households (id, name) VALUES (?, ?)",
                [DEFAULT_HOUSEHOLD_ID, DEFAULT_HOUSEHOLD_NAME],
            )

        # Seed default store layout (standard grocery flow) if empty for default household
        existing_layout = conn.execute(
            "SELECT 1 FROM store_layout WHERE household_id = ? LIMIT 1",
            [DEFAULT_HOUSEHOLD_ID],
        ).fetchone()
        if not existing_layout:
            default_order = [
                "Fruits", "Vegetables", "Dairy & Eggs", "Meat & Poultry",
                "Fish & Seafood", "Protein", "Grains", "Legumes & Nuts",
                "Oils & Fats", "Sauces & Condiments", "Seasonings", "Other",
            ]
            conn.executemany(
                "INSERT INTO store_layout (household_id, category, sort_index) VALUES (?, ?, ?)",
                [(DEFAULT_HOUSEHOLD_ID, cat, i) for i, cat in enumerate(default_order)],
            )

        # Seed ingredient unit overrides if empty
        existing_units = conn.execute("SELECT 1 FROM ingredient_units LIMIT 1").fetchone()
        if not existing_units:
            # (fdc_id, display_unit, grams_per_unit, round_step)
            seed_units = [
                # Dairy & Eggs
                (171287, "pcs", 50, 1),        # Egg
                (171265, "dl", 100, 0.5),      # Milk (whole) — 1 dl ≈ 100g
                (170859, "dl", 100, 0.5),      # Cream
                (171284, "dl", 100, 0.5),      # Yogurt
                # Oils / liquids
                (171413, "dl", 92, 0.1),       # Olive oil
                (172336, "dl", 92, 0.1),       # Vegetable oil
                (174278, "dl", 115, 0.5),      # Soy sauce
                (172237, "dl", 100, 0.5),      # Vinegar
                (170054, "dl", 105, 0.5),      # Tomato sauce
                # Dry pantry with volume buying habit
                (168936, "dl", 60, 0.5),       # Flour (all-purpose)
                (169655, "dl", 85, 0.5),       # Sugar
                (168877, "dl", 80, 0.5),       # Rice (white)
                (169703, "dl", 80, 0.5),       # Rice (brown)
                (173904, "dl", 35, 0.5),       # Oats
                # Produce by piece
                (169230, "clove", 5, 1),       # Garlic
                (170000, "pcs", 150, 1),       # Onion
                (170393, "pcs", 60, 1),        # Carrot
                (170026, "pcs", 150, 1),       # Potato
                (168482, "pcs", 150, 1),       # Sweet potato
                (167746, "pcs", 60, 1),        # Lemon
                (171688, "pcs", 180, 1),       # Apple
                (173944, "pcs", 120, 1),       # Banana
                (169917, "pcs", 130, 1),       # Orange
                (171705, "pcs", 170, 1),       # Avocado
                (170108, "pcs", 150, 1),       # Bell pepper
                (170457, "pcs", 120, 1),       # Tomato
                (168409, "pcs", 300, 1),       # Cucumber
                (169291, "pcs", 200, 1),       # Zucchini
                (169228, "pcs", 300, 1),       # Eggplant
            ]
            conn.executemany(
                "INSERT INTO ingredient_units (fdc_id, display_unit, grams_per_unit, round_step) "
                "VALUES (?, ?, ?, ?)",
                seed_units,
            )


# Initialize on import
init_db()
