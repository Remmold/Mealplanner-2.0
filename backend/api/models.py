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


class Ingredient(BaseModel):
    fdc_id: int
    name: str
    food_group: str
    subcategory: str | None = None
    energy_kcal_100g: float | None = None
    proteins_100g: float | None = None
    carbohydrates_100g: float | None = None
    sugars_100g: float | None = None
    fat_100g: float | None = None
    saturated_fat_100g: float | None = None
    fiber_100g: float | None = None
    salt_100g: float | None = None


class NutritionItem(BaseModel):
    code: str
    quantity_g: float


class RecipeItem(BaseModel):
    fdc_id: int
    quantity_g: float


class RecipeNutrition(BaseModel):
    total_energy_kcal: float
    total_proteins_g: float
    total_carbohydrates_g: float
    total_sugars_g: float
    total_fat_g: float
    total_saturated_fat_g: float
    total_fiber_g: float
    total_salt_g: float
    total_weight_g: float
    items_found: int
    items_missing: list[int]


# --- Recipe CRUD models ---


class RecipeIngredientIn(BaseModel):
    fdc_id: int
    quantity_g: float


class RecipeCreate(BaseModel):
    name: str
    ingredients: list[RecipeIngredientIn] = []
    instructions: list[str] = []
    servings: int = 4


class RecipeUpdate(BaseModel):
    name: str | None = None
    ingredients: list[RecipeIngredientIn] | None = None
    instructions: list[str] | None = None
    servings: int | None = None


class GenerateRecipeRequest(BaseModel):
    prompt: str


class GeneratedIngredientOut(BaseModel):
    fdc_id: int
    name: str
    quantity_g: float


class GeneratedRecipeOut(BaseModel):
    name: str
    ingredients: list[GeneratedIngredientOut]
    instructions: list[str]


class RecipeIngredientOut(BaseModel):
    fdc_id: int
    quantity_g: float
    ingredient_name: str | None = None


class RecipeOut(BaseModel):
    id: str
    household_id: str
    name: str
    ingredients: list[RecipeIngredientOut] = []
    instructions: list[str] = []
    servings: int = 4
    image_path: str | None = None
    created_at: str
    updated_at: str


# --- Shopping list models ---


class ShoppingRecipeSelection(BaseModel):
    recipe_id: str
    portions: float


class ShoppingListItem(BaseModel):
    fdc_id: int
    name: str
    category: str
    quantity_g: float
    display_quantity: float
    display_unit: str


class ShoppingListCategory(BaseModel):
    category: str
    sort_index: int
    items: list[ShoppingListItem]


class ShoppingListOut(BaseModel):
    categories: list[ShoppingListCategory]
    missing_recipes: list[str] = []


# --- Meal plan models ---


class MealPlanEntryIn(BaseModel):
    recipe_id: str
    plan_date: str  # ISO date, e.g. "2026-04-14"
    slot: str | None = None  # "breakfast" | "lunch" | "dinner" | None
    portions: float = 1


class MealPlanCreate(BaseModel):
    name: str
    start_date: str  # ISO date
    entries: list[MealPlanEntryIn] = []


class MealPlanUpdate(BaseModel):
    name: str | None = None
    start_date: str | None = None
    entries: list[MealPlanEntryIn] | None = None


class MealPlanEntryOut(BaseModel):
    id: str
    recipe_id: str
    recipe_name: str | None = None
    plan_date: str
    slot: str | None = None
    portions: float


class MealPlanOut(BaseModel):
    id: str
    household_id: str
    name: str
    start_date: str
    entries: list[MealPlanEntryOut] = []
    created_at: str
    updated_at: str


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
