const BASE = "/api";

export interface ProductSummary {
  code: string;
  product_name: string;
  brands: string | null;
  category_label: string | null;
  subcategory: string | null;
  nutriscore_grade: string | null;
  energy_kcal_100g: number | null;
  proteins_100g: number | null;
  image_url: string | null;
  data_completeness: number | null;
}

export interface PaginatedProducts {
  items: ProductSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface Product extends ProductSummary {
  primary_category: string | null;
  categories: string[];
  allergens: string[];
  countries: string[];
  ingredients_text: string | null;
  nova_group: number | null;
  serving_size: string | null;
  serving_quantity_g: number | null;
  carbohydrates_100g: number | null;
  sugars_100g: number | null;
  fat_100g: number | null;
  saturated_fat_100g: number | null;
  fiber_100g: number | null;
  salt_100g: number | null;
  sodium_100g: number | null;
  protein_level: string | null;
  fat_level: string | null;
  sugar_level: string | null;
  fiber_level: string | null;
  is_high_nutriscore: boolean | null;
  is_minimally_processed: boolean | null;
  is_high_protein: boolean | null;
  is_low_calorie: boolean | null;
  is_gluten_free: boolean | null;
  is_dairy_free: boolean | null;
  is_egg_free: boolean | null;
  is_nut_free: boolean | null;
  is_seafood_free: boolean | null;
  data_completeness: number | null;
  last_modified_at: string | null;
}

export interface AggregatedNutrition {
  total_energy_kcal: number;
  total_proteins_g: number;
  total_carbohydrates_g: number;
  total_sugars_g: number;
  total_fat_g: number;
  total_saturated_fat_g: number;
  total_fiber_g: number;
  total_salt_g: number;
  total_weight_g: number;
  products_found: number;
  products_missing: string[];
}

export async function fetchProducts(params: Record<string, string>): Promise<PaginatedProducts> {
  const qs = new URLSearchParams(params).toString();
  const res = await fetch(`${BASE}/products?${qs}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function fetchProduct(code: string): Promise<Product> {
  const res = await fetch(`${BASE}/products/${encodeURIComponent(code)}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function fetchCategories(): Promise<string[]> {
  const res = await fetch(`${BASE}/categories`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function fetchSubcategories(): Promise<string[]> {
  const res = await fetch(`${BASE}/subcategories`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function aggregateNutrition(
  items: { code: string; quantity_g: number }[]
): Promise<AggregatedNutrition> {
  const res = await fetch(`${BASE}/nutrition/aggregate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(items),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

// --- USDA Generic Ingredients ---

export interface Ingredient {
  fdc_id: number;
  name: string;
  food_group: string;
  subcategory: string | null;
  energy_kcal_100g: number | null;
  proteins_100g: number | null;
  carbohydrates_100g: number | null;
  sugars_100g: number | null;
  fat_100g: number | null;
  saturated_fat_100g: number | null;
  fiber_100g: number | null;
  salt_100g: number | null;
}

export interface RecipeNutrition {
  total_energy_kcal: number;
  total_proteins_g: number;
  total_carbohydrates_g: number;
  total_sugars_g: number;
  total_fat_g: number;
  total_saturated_fat_g: number;
  total_fiber_g: number;
  total_salt_g: number;
  total_weight_g: number;
  items_found: number;
  items_missing: number[];
}

export async function fetchIngredientCategories(): Promise<string[]> {
  const res = await fetch(`${BASE}/ingredients/categories`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function fetchIngredients(params?: Record<string, string>): Promise<Ingredient[]> {
  const qs = params ? new URLSearchParams(params).toString() : "";
  const res = await fetch(`${BASE}/ingredients${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function aggregateRecipe(
  items: { fdc_id: number; quantity_g: number }[]
): Promise<RecipeNutrition> {
  const res = await fetch(`${BASE}/ingredients/aggregate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(items),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}
