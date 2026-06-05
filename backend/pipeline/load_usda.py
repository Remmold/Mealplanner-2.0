"""Load USDA SR Legacy CSV data into DuckDB as a single denormalized table."""

from pathlib import Path

import duckdb

USDA_DIR = Path(__file__).resolve().parent.parent / "usda_data" / "FoodData_Central_sr_legacy_food_csv_2018-04"
DB_PATH = Path(__file__).resolve().parent.parent / "food_data.duckdb"

# Nutrient IDs we care about (from nutrient.csv)
NUTRIENT_IDS = {
    1008: "energy_kcal_100g",
    1003: "proteins_100g",
    1005: "carbohydrates_100g",
    2000: "sugars_100g",        # Sugars, Total
    1004: "fat_100g",           # Total lipid (fat)
    1258: "saturated_fat_100g", # Fatty acids, total saturated
    1079: "fiber_100g",         # Fiber, total dietary
    1093: "sodium_mg_100g",     # Sodium, Na (in mg)
}


def main():
    conn = duckdb.connect(str(DB_PATH))

    conn.execute("CREATE SCHEMA IF NOT EXISTS usda")

    # Load raw CSVs into staging tables
    conn.execute(f"""
        CREATE OR REPLACE TABLE usda.raw_food AS
        SELECT * FROM read_csv_auto('{USDA_DIR}/food.csv', header=true)
    """)
    conn.execute(f"""
        CREATE OR REPLACE TABLE usda.raw_food_category AS
        SELECT * FROM read_csv_auto('{USDA_DIR}/food_category.csv', header=true)
    """)
    conn.execute(f"""
        CREATE OR REPLACE TABLE usda.raw_food_nutrient AS
        SELECT * FROM read_csv_auto('{USDA_DIR}/food_nutrient.csv', header=true)
    """)
    conn.execute(f"""
        CREATE OR REPLACE TABLE usda.raw_nutrient AS
        SELECT * FROM read_csv_auto('{USDA_DIR}/nutrient.csv', header=true)
    """)
    conn.execute(f"""
        CREATE OR REPLACE TABLE usda.raw_food_portion AS
        SELECT * FROM read_csv_auto('{USDA_DIR}/food_portion.csv', header=true)
    """)

    # Build the pivoted nutrients per food
    nutrient_id_list = ", ".join(str(nid) for nid in NUTRIENT_IDS)
    pivot_cases = "\n".join(
        f"        max(CASE WHEN fn.nutrient_id = {nid} THEN fn.amount END) AS {col},"
        for nid, col in NUTRIENT_IDS.items()
    )
    # Remove trailing comma from last line
    pivot_cases = pivot_cases.rstrip(",")

    conn.execute(f"""
        CREATE OR REPLACE TABLE usda.ingredients AS
        WITH nutrients AS (
            SELECT
                fn.fdc_id,
    {pivot_cases}
            FROM usda.raw_food_nutrient fn
            WHERE fn.nutrient_id IN ({nutrient_id_list})
            GROUP BY fn.fdc_id
        )
        SELECT
            f.fdc_id,
            f.description AS name,
            fc.description AS food_group,
            n.energy_kcal_100g,
            n.proteins_100g,
            n.carbohydrates_100g,
            n.sugars_100g,
            n.fat_100g,
            n.saturated_fat_100g,
            n.fiber_100g,
            n.sodium_mg_100g,
            round(n.sodium_mg_100g * 2.5 / 1000, 2) AS salt_100g
        FROM usda.raw_food f
        JOIN usda.raw_food_category fc ON fc.id = f.food_category_id
        LEFT JOIN nutrients n ON n.fdc_id = f.fdc_id
    """)

    count = conn.execute("SELECT count(*) FROM usda.ingredients").fetchone()[0]
    groups = conn.execute("SELECT count(DISTINCT food_group) FROM usda.ingredients").fetchone()[0]

    print(f"Loaded {count} USDA ingredients across {groups} food groups into usda.ingredients")

    # Show some examples
    rows = conn.execute("""
        SELECT name, food_group, energy_kcal_100g, proteins_100g
        FROM usda.ingredients
        ORDER BY name
        LIMIT 10
    """).fetchall()
    for row in rows:
        print(f"  {row[0]:<50} {row[1]:<30} {row[2]} kcal  {row[3]}g protein")

    conn.close()


if __name__ == "__main__":
    main()
