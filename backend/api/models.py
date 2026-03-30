from pydantic import BaseModel


class Product(BaseModel):
    code: str
    product_name: str
    brands: str | None = None
    primary_category: str | None = None
    category_label: str | None = None
    subcategory: str | None = None
    categories: list[str] = []
    allergens: list[str] = []
    countries: list[str] = []
    ingredients_text: str | None = None
    image_url: str | None = None

    # Quality scores
    nutriscore_grade: str | None = None
    nova_group: int | None = None

    # Serving info
    serving_size: str | None = None
    serving_quantity_g: float | None = None

    # Nutrition per 100g
    energy_kcal_100g: float | None = None
    proteins_100g: float | None = None
    carbohydrates_100g: float | None = None
    sugars_100g: float | None = None
    fat_100g: float | None = None
    saturated_fat_100g: float | None = None
    fiber_100g: float | None = None
    salt_100g: float | None = None
    sodium_100g: float | None = None

    # Macro level labels
    protein_level: str | None = None
    fat_level: str | None = None
    sugar_level: str | None = None
    fiber_level: str | None = None

    # Quality / processing flags
    is_high_nutriscore: bool | None = None
    is_minimally_processed: bool | None = None
    is_high_protein: bool | None = None
    is_low_calorie: bool | None = None

    # Dietary flags
    is_gluten_free: bool | None = None
    is_dairy_free: bool | None = None
    is_egg_free: bool | None = None
    is_nut_free: bool | None = None
    is_seafood_free: bool | None = None

    # Meta
    data_completeness: float | None = None
    last_modified_at: str | None = None


class ProductSummary(BaseModel):
    code: str
    product_name: str
    brands: str | None = None
    category_label: str | None = None
    subcategory: str | None = None
    nutriscore_grade: str | None = None
    energy_kcal_100g: float | None = None
    proteins_100g: float | None = None
    image_url: str | None = None
    data_completeness: float | None = None


class PaginatedProducts(BaseModel):
    items: list[ProductSummary]
    total: int
    page: int
    page_size: int


class NutritionItem(BaseModel):
    code: str
    quantity_g: float


class AggregatedNutrition(BaseModel):
    total_energy_kcal: float
    total_proteins_g: float
    total_carbohydrates_g: float
    total_sugars_g: float
    total_fat_g: float
    total_saturated_fat_g: float
    total_fiber_g: float
    total_salt_g: float
    total_weight_g: float
    products_found: int
    products_missing: list[str]
