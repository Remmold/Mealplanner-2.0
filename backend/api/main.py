from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from api.database import get_connection
from api.recipes import router as recipes_router
from api.shopping import router as shopping_router
from api.ingredients import router as ingredients_router, load_all_curated_meta
from api.meal_plans import router as meal_plans_router
from api.models import (
    AggregatedNutrition,
    Ingredient,
    NutritionItem,
    PaginatedProducts,
    Product,
    ProductSummary,
    RecipeItem,
    RecipeNutrition,
)

app = FastAPI(title="Mealplanner API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(recipes_router)
app.include_router(shopping_router)
app.include_router(ingredients_router)
app.include_router(meal_plans_router)


SUMMARY_COLUMNS = """
    code, product_name, brands, category_label, subcategory,
    nutriscore_grade, energy_kcal_100g, proteins_100g,
    image_url, data_completeness
"""

PRODUCT_SCHEMA = "main_marts"
PRODUCT_TABLE = "dim_products"


# READ: List products with optional search, filtering, sorting, and pagination.
@app.get("/products", response_model=PaginatedProducts)
def list_products(
    search: str | None = Query(None, description="Search product name or brand"),
    category: str | None = Query(None, description="Filter by category_label (exact)"),
    subcategory: str | None = Query(None, description="Filter by subcategory (exact)"),
    nutriscore: str | None = Query(None, description="Filter by nutriscore grade (a-e)"),
    is_high_protein: bool | None = Query(None),
    is_low_calorie: bool | None = Query(None),
    is_gluten_free: bool | None = Query(None),
    is_dairy_free: bool | None = Query(None),
    is_nut_free: bool | None = Query(None),
    is_seafood_free: bool | None = Query(None),
    min_data_completeness: float | None = Query(None, ge=0, le=1),
    sort_by: str = Query("data_completeness", description="Column to sort by"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    allowed_sort = {
        "product_name", "energy_kcal_100g", "proteins_100g",
        "data_completeness", "nutriscore_grade",
    }
    if sort_by not in allowed_sort:
        raise HTTPException(400, f"sort_by must be one of {allowed_sort}")

    conditions: list[str] = []
    params: list = []

    if search:
        conditions.append("(product_name ILIKE ? OR brands ILIKE ?)")
        params += [f"%{search}%", f"%{search}%"]
    if category:
        conditions.append("category_label = ?")
        params.append(category)
    if subcategory:
        conditions.append("subcategory = ?")
        params.append(subcategory)
    if nutriscore:
        conditions.append("nutriscore_grade = ?")
        params.append(nutriscore.lower())
    for flag_name, flag_val in [
        ("is_high_protein", is_high_protein),
        ("is_low_calorie", is_low_calorie),
        ("is_gluten_free", is_gluten_free),
        ("is_dairy_free", is_dairy_free),
        ("is_nut_free", is_nut_free),
        ("is_seafood_free", is_seafood_free),
    ]:
        if flag_val is not None:
            conditions.append(f"{flag_name} = ?")
            params.append(flag_val)
    if min_data_completeness is not None:
        conditions.append("data_completeness >= ?")
        params.append(min_data_completeness)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    with get_connection() as conn:
        total = conn.execute(
            f"SELECT count(*) FROM {PRODUCT_SCHEMA}.{PRODUCT_TABLE} {where}", params
        ).fetchone()[0]

        offset = (page - 1) * page_size
        rows = conn.execute(
            f"SELECT {SUMMARY_COLUMNS} FROM {PRODUCT_SCHEMA}.{PRODUCT_TABLE} "
            f"{where} ORDER BY {sort_by} {sort_order} "
            f"LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()

        columns = [
            "code", "product_name", "brands", "category_label", "subcategory",
            "nutriscore_grade", "energy_kcal_100g", "proteins_100g",
            "image_url", "data_completeness",
        ]
        items = [ProductSummary(**dict(zip(columns, row))) for row in rows]

    return PaginatedProducts(items=items, total=total, page=page, page_size=page_size)


# READ: Fetch a single product's full detail by its barcode.
@app.get("/products/{code}", response_model=Product)
def get_product(code: str):
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT * FROM {PRODUCT_SCHEMA}.{PRODUCT_TABLE} WHERE code = ?", [code]
        ).fetchone()
        if not row:
            raise HTTPException(404, "Product not found")
        columns = [desc[0] for desc in conn.description]
        data = dict(zip(columns, row))

    # Convert DuckDB list objects to plain Python lists
    for key in ("categories", "allergens", "countries"):
        if data.get(key) is not None:
            data[key] = list(data[key])
        else:
            data[key] = []

    if data.get("last_modified_at") is not None:
        data["last_modified_at"] = str(data["last_modified_at"])

    return Product(**data)


# READ: List all distinct product categories available in the database.
@app.get("/categories", response_model=list[str])
def list_categories():
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT DISTINCT category_label FROM {PRODUCT_SCHEMA}.{PRODUCT_TABLE} "
            "WHERE category_label IS NOT NULL ORDER BY category_label"
        ).fetchall()
    return [row[0] for row in rows]


# READ: List all distinct product subcategories available in the database.
@app.get("/subcategories", response_model=list[str])
def list_subcategories():
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT DISTINCT subcategory FROM {PRODUCT_SCHEMA}.{PRODUCT_TABLE} "
            "WHERE subcategory IS NOT NULL ORDER BY subcategory"
        ).fetchall()
    return [row[0] for row in rows]


INGREDIENT_SCHEMA = "usda"
INGREDIENT_TABLE = "ingredients"


# READ: List ingredient categories (dbt seed ∪ pantry promotions).
@app.get("/ingredients/categories", response_model=list[str])
def list_ingredient_categories():
    meta = load_all_curated_meta()
    return sorted({m["category"] for m in meta.values()})


# READ: List curated common ingredients with USDA nutrition data (dbt seed ∪ pantry).
@app.get("/ingredients", response_model=list[Ingredient])
def list_ingredients(
    search: str | None = Query(None, description="Filter by name"),
    category: str | None = Query(None, description="Filter by ingredient category"),
):
    meta = load_all_curated_meta()
    if not meta:
        return []

    fdc_ids = list(meta.keys())
    placeholders = ", ".join(["?"] * len(fdc_ids))
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT fdc_id, energy_kcal_100g, proteins_100g, carbohydrates_100g, sugars_100g, "
            f"fat_100g, saturated_fat_100g, fiber_100g, salt_100g "
            f"FROM {INGREDIENT_SCHEMA}.{INGREDIENT_TABLE} "
            f"WHERE fdc_id IN ({placeholders})",
            fdc_ids,
        ).fetchall()
    nutri = {r[0]: r for r in rows}

    search_lc = search.lower() if search else None
    results: list[Ingredient] = []
    for fdc_id, info in meta.items():
        if category and info["category"] != category:
            continue
        if search_lc and search_lc not in info["simple_name"].lower():
            continue
        n = nutri.get(fdc_id)
        if not n:
            continue
        results.append(Ingredient(
            fdc_id=fdc_id,
            name=info["simple_name"],
            food_group=info["category"],
            subcategory=info["subcategory"] or None,
            energy_kcal_100g=n[1], proteins_100g=n[2], carbohydrates_100g=n[3],
            sugars_100g=n[4], fat_100g=n[5], saturated_fat_100g=n[6],
            fiber_100g=n[7], salt_100g=n[8],
        ))
    results.sort(key=lambda i: (i.food_group, i.name.lower()))
    return results


# READ: Aggregate nutritional values for generic ingredients scaled by quantity (in grams).
@app.post("/ingredients/aggregate", response_model=RecipeNutrition)
def aggregate_recipe(items: list[RecipeItem]):
    if not items:
        raise HTTPException(400, "At least one item is required")

    fdc_ids = [item.fdc_id for item in items]
    qty_map = {item.fdc_id: item.quantity_g for item in items}

    placeholders = ", ".join(["?"] * len(fdc_ids))
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT fdc_id, energy_kcal_100g, proteins_100g, carbohydrates_100g, "
            f"sugars_100g, fat_100g, saturated_fat_100g, fiber_100g, salt_100g "
            f"FROM {INGREDIENT_SCHEMA}.{INGREDIENT_TABLE} "
            f"WHERE fdc_id IN ({placeholders})",
            fdc_ids,
        ).fetchall()

    found_ids = set()
    totals = dict(
        total_energy_kcal=0.0, total_proteins_g=0.0, total_carbohydrates_g=0.0,
        total_sugars_g=0.0, total_fat_g=0.0, total_saturated_fat_g=0.0,
        total_fiber_g=0.0, total_salt_g=0.0, total_weight_g=0.0,
    )
    nutrient_keys = [
        "total_energy_kcal", "total_proteins_g", "total_carbohydrates_g",
        "total_sugars_g", "total_fat_g", "total_saturated_fat_g",
        "total_fiber_g", "total_salt_g",
    ]

    for row in rows:
        fdc_id = row[0]
        found_ids.add(fdc_id)
        qty = qty_map[fdc_id]
        factor = qty / 100.0
        totals["total_weight_g"] += qty
        for i, key in enumerate(nutrient_keys):
            val = row[i + 1]
            if val is not None:
                totals[key] += val * factor

    totals = {k: round(v, 1) for k, v in totals.items()}

    return RecipeNutrition(
        **totals,
        items_found=len(found_ids),
        items_missing=[fid for fid in fdc_ids if fid not in found_ids],
    )


# READ: Aggregate nutritional values for a list of products scaled by quantity (in grams).
@app.post("/nutrition/aggregate", response_model=AggregatedNutrition)
def aggregate_nutrition(items: list[NutritionItem]):
    if not items:
        raise HTTPException(400, "At least one item is required")

    codes = [item.code for item in items]
    qty_map = {item.code: item.quantity_g for item in items}

    placeholders = ", ".join(["?"] * len(codes))
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT code, energy_kcal_100g, proteins_100g, carbohydrates_100g, "
            f"sugars_100g, fat_100g, saturated_fat_100g, fiber_100g, salt_100g "
            f"FROM {PRODUCT_SCHEMA}.{PRODUCT_TABLE} WHERE code IN ({placeholders})",
            codes,
        ).fetchall()

    found_codes = set()
    totals = dict(
        total_energy_kcal=0.0,
        total_proteins_g=0.0,
        total_carbohydrates_g=0.0,
        total_sugars_g=0.0,
        total_fat_g=0.0,
        total_saturated_fat_g=0.0,
        total_fiber_g=0.0,
        total_salt_g=0.0,
        total_weight_g=0.0,
    )

    nutrient_keys = [
        "total_energy_kcal", "total_proteins_g", "total_carbohydrates_g",
        "total_sugars_g", "total_fat_g", "total_saturated_fat_g",
        "total_fiber_g", "total_salt_g",
    ]

    for row in rows:
        code = row[0]
        found_codes.add(code)
        qty = qty_map[code]
        factor = qty / 100.0
        totals["total_weight_g"] += qty
        for i, key in enumerate(nutrient_keys):
            val = row[i + 1]
            if val is not None:
                totals[key] += val * factor

    # Round all values
    totals = {k: round(v, 1) for k, v in totals.items()}

    return AggregatedNutrition(
        **totals,
        products_found=len(found_codes),
        products_missing=[c for c in codes if c not in found_codes],
    )
