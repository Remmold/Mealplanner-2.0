const BASE = "/api";

// ------------------------------------------------------------------
// Cross-component refresh signal
// ------------------------------------------------------------------
// The chat agent can mutate recipes / meal plans / pantry behind the user's
// back. Components subscribe to this so they refetch after agent turns or
// other writes. Dispatch with `dataChanged()` after any mutation that other
// views might care about.
type DataKind = "recipes" | "meal_plans" | "pantry" | "*";

const listeners = new Set<(kind: DataKind) => void>();

export function dataChanged(kind: DataKind = "*") {
  for (const l of listeners) {
    try { l(kind); } catch {}
  }
}

export function onDataChanged(handler: (kind: DataKind) => void): () => void {
  listeners.add(handler);
  return () => listeners.delete(handler);
}

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

// --- Recipe CRUD ---

export interface RecipeIngredient {
  fdc_id: number;
  quantity_g: number;
  ingredient_name: string | null;
}

export interface Recipe {
  id: string;
  household_id: string;
  name: string;
  ingredients: RecipeIngredient[];
  instructions: string[];
  servings: number;
  created_at: string;
  updated_at: string;
}

export async function fetchRecipes(): Promise<Recipe[]> {
  const res = await fetch(`${BASE}/recipes`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function fetchRecipe(id: string): Promise<Recipe> {
  const res = await fetch(`${BASE}/recipes/${id}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function createRecipe(
  name: string,
  ingredients: { fdc_id: number; quantity_g: number }[],
  instructions: string[] = [],
  servings: number = 4
): Promise<Recipe> {
  const res = await fetch(`${BASE}/recipes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, ingredients, instructions, servings }),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function updateRecipe(
  id: string,
  data: {
    name?: string;
    ingredients?: { fdc_id: number; quantity_g: number }[];
    instructions?: string[];
    servings?: number;
  }
): Promise<Recipe> {
  const res = await fetch(`${BASE}/recipes/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function deleteRecipe(id: string): Promise<void> {
  const res = await fetch(`${BASE}/recipes/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
}

// --- Recipe Generation ---

export interface GeneratedIngredient {
  fdc_id: number;
  name: string;
  quantity_g: number;
}

export interface GeneratedRecipe {
  name: string;
  ingredients: GeneratedIngredient[];
  instructions: string[];
}

export async function generateRecipe(prompt: string): Promise<GeneratedRecipe> {
  const res = await fetch(`${BASE}/recipes/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

// --- Shopping list ---

export interface ShoppingListItem {
  fdc_id: number;
  name: string;
  category: string;
  quantity_g: number;
  display_quantity: number;
  display_unit: string;
}

export interface ShoppingListCategory {
  category: string;
  sort_index: number;
  items: ShoppingListItem[];
}

export interface ShoppingList {
  categories: ShoppingListCategory[];
  missing_recipes: string[];
}

export async function generateShoppingList(
  selections: { recipe_id: string; portions: number }[]
): Promise<ShoppingList> {
  const res = await fetch(`${BASE}/shopping-lists/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(selections),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function fetchStoreLayout(): Promise<string[]> {
  const res = await fetch(`${BASE}/shopping-lists/store-layout`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

// --- USDA search & pantry ---

export interface UsdaSearchResult {
  fdc_id: number;
  name: string;
  food_group: string | null;
  mapped_category: string;
  energy_kcal_100g: number | null;
  proteins_100g: number | null;
  in_pantry: boolean;
}

export interface PantryEntry {
  fdc_id: number;
  simple_name: string;
  category: string;
  subcategory: string | null;
}

export async function searchUsda(query: string, limit = 50): Promise<UsdaSearchResult[]> {
  const qs = new URLSearchParams({ q: query, limit: String(limit) }).toString();
  const res = await fetch(`${BASE}/ingredients/usda-search?${qs}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function addToPantry(
  fdc_id: number,
  simple_name?: string,
  category?: string
): Promise<PantryEntry> {
  const res = await fetch(`${BASE}/pantry`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fdc_id, simple_name, category }),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function updateStoreLayout(categories: string[]): Promise<string[]> {
  const res = await fetch(`${BASE}/shopping-lists/store-layout`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(categories),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

// --- Meal plans ---

export interface MealPlanEntry {
  id: string;
  recipe_id: string;
  recipe_name: string | null;
  plan_date: string;
  slot: string | null;
  portions: number;
}

export interface MealPlan {
  id: string;
  household_id: string;
  name: string;
  start_date: string;
  entries: MealPlanEntry[];
  created_at: string;
  updated_at: string;
}

export interface MealPlanEntryInput {
  recipe_id: string;
  plan_date: string;
  slot?: string | null;
  portions: number;
}

export async function fetchMealPlans(): Promise<MealPlan[]> {
  const res = await fetch(`${BASE}/meal-plans`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function createMealPlan(
  name: string,
  start_date: string,
  entries: MealPlanEntryInput[] = []
): Promise<MealPlan> {
  const res = await fetch(`${BASE}/meal-plans`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, start_date, entries }),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function updateMealPlan(
  id: string,
  data: { name?: string; start_date?: string; entries?: MealPlanEntryInput[] }
): Promise<MealPlan> {
  const res = await fetch(`${BASE}/meal-plans/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function deleteMealPlan(id: string): Promise<void> {
  const res = await fetch(`${BASE}/meal-plans/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
}

export interface GenerateMealPlanInput {
  prompt: string;
  start_date: string;
  days?: number;
  servings?: number;
  slots?: string[];
}

export async function generateMealPlan(input: GenerateMealPlanInput): Promise<MealPlan> {
  const res = await fetch(`${BASE}/meal-plans/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function mealPlanShoppingList(id: string): Promise<ShoppingList> {
  const res = await fetch(`${BASE}/meal-plans/${id}/shopping-list`, { method: "POST" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

// --- Chat ---

export interface ChatSessionSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface ChatSessionDetail {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: ChatMessage[];
}

export interface ChatAuditEvent {
  kind: string;
  summary: string;
  meta: Record<string, unknown>;
}

export interface SendMessageResponse {
  reply: string;
  audit: ChatAuditEvent[];
  session_id: string;
}

export async function listChatSessions(): Promise<ChatSessionSummary[]> {
  const res = await fetch(`${BASE}/chat/sessions`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function createChatSession(): Promise<ChatSessionDetail> {
  const res = await fetch(`${BASE}/chat/sessions`, { method: "POST" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function getChatSession(id: string): Promise<ChatSessionDetail> {
  const res = await fetch(`${BASE}/chat/sessions/${id}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function deleteChatSession(id: string): Promise<void> {
  const res = await fetch(`${BASE}/chat/sessions/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
}

export async function sendChatMessage(id: string, content: string): Promise<SendMessageResponse> {
  const res = await fetch(`${BASE}/chat/sessions/${id}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}
