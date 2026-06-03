import { supabase } from "./lib/supabase";

const BASE = "/api";

// ------------------------------------------------------------------
// Auth-injecting fetch wrapper. Every request to the backend carries the
// authenticated user's Supabase JWT so the backend can resolve the
// current household via Depends(get_current_household_id).
// Pre-pends BASE so call sites just pass the path ("/recipes", etc.).
// ------------------------------------------------------------------
async function authFetch(path: string, init?: RequestInit): Promise<Response> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string> | undefined) ?? {}),
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  return fetch(`${BASE}${path}`, { ...init, headers });
}

// ------------------------------------------------------------------
// Cross-component refresh signal
// ------------------------------------------------------------------
// The chat agent can mutate recipes / meal plans / pantry behind the user's
// back. Components subscribe to this so they refetch after agent turns or
// other writes. Dispatch with `dataChanged()` after any mutation that other
// views might care about.
type DataKind = "recipes" | "meal_plans" | "meals" | "pantry" | "*";

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

// ------------------------------------------------------------------
// Navigation intents — used by chat cards / inline chat links to jump
// to a related view. `openGenerator` on the plan intent additionally
// triggers the weekly-plan wizard on arrival.
// ------------------------------------------------------------------
export type NavIntent =
  | { tab: "recipe"; recipe_id?: string }
  | { tab: "plan"; plan_id?: string; openGenerator?: boolean; week_start?: string }
  | { tab: "shopping" }
  | { tab: "profile" }
  | { tab: "explore"; slot?: SlotFilter };

const navListeners = new Set<(intent: NavIntent) => void>();
export function navigateTo(intent: NavIntent) {
  for (const l of navListeners) { try { l(intent); } catch {} }
}
export function onNavigate(handler: (intent: NavIntent) => void): () => void {
  navListeners.add(handler);
  return () => navListeners.delete(handler);
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
  const res = await authFetch(`/ingredients/categories`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function fetchIngredients(params?: Record<string, string>): Promise<Ingredient[]> {
  const qs = params ? new URLSearchParams(params).toString() : "";
  const res = await authFetch(`/ingredients${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function aggregateRecipe(
  items: { fdc_id: number; quantity_g: number }[]
): Promise<RecipeNutrition> {
  const res = await authFetch(`/ingredients/aggregate`, {
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
  from_pantry?: boolean;
}

export interface Recipe {
  id: string;
  household_id: string;
  name: string;
  ingredients: RecipeIngredient[];
  instructions: string[];
  servings: number;
  meal_type: "breakfast" | "lunch" | "dinner" | null;
  image_path: string | null;
  created_at: string;
  updated_at: string;
}

export async function regenerateRecipeImage(recipeId: string): Promise<void> {
  const res = await authFetch(`/recipes/${recipeId}/image/regenerate`, { method: "POST" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
}

export async function fetchRecipes(): Promise<Recipe[]> {
  const res = await authFetch(`/recipes`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function fetchRecipe(id: string): Promise<Recipe> {
  const res = await authFetch(`/recipes/${id}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function createRecipe(
  name: string,
  ingredients: { fdc_id: number; quantity_g: number }[],
  instructions: string[] = [],
  servings: number = 4,
  meal_type: "breakfast" | "lunch" | "dinner" | null = null,
): Promise<Recipe> {
  const res = await authFetch(`/recipes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, ingredients, instructions, servings, meal_type }),
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
    meal_type?: "breakfast" | "lunch" | "dinner" | null;
  }
): Promise<Recipe> {
  const res = await authFetch(`/recipes/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function deleteRecipe(id: string): Promise<void> {
  const res = await authFetch(`/recipes/${id}`, { method: "DELETE" });
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
  const res = await authFetch(`/recipes/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

/** Seed N profile-matched starter recipes into the current household.
 *  Idempotent: skips recipes the household already has by name.
 *  Returns the names that were actually created. */
export async function seedStarterRecipes(count: number = 12): Promise<string[]> {
  const qs = new URLSearchParams({ count: String(count) }).toString();
  const res = await authFetch(`/recipes/seed-starters?${qs}`, { method: "POST" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  const body = await res.json();
  return body.created as string[];
}

// --- Explore (Tinder-style recipe discovery) ---

export type SlotFilter = "any" | "breakfast" | "lunch" | "dinner";

export interface ExploreCard {
  id: string;
  name: string;
  meal_type: "breakfast" | "lunch" | "dinner" | null;
  cuisine: string[];
  dietary: string[];
  time_min: number | null;
  source: "starter_corpus" | "llm" | "household_share";
  image_path: string | null;
  ingredients_preview: string[];
  ingredient_count: number;
  step_count: number;
  match_reasons: string[];
}

export interface SwipeResult {
  saved_recipe_id: string | null;
  saved_recipe_name: string | null;
  profile_added_cuisines: string[];
}

export interface ExploreStats {
  likes: number;
  skips: number;
  pool_size: number;
}

export interface ExploreRecipeDetail {
  id: string;
  name: string;
  meal_type: "breakfast" | "lunch" | "dinner" | null;
  cuisine: string[];
  dietary: string[];
  time_min: number | null;
  source: "starter_corpus" | "llm" | "household_share";
  image_path: string | null;
  ingredients: Array<{
    fdc_id: number;
    name: string | null;
    quantity_g: number;
    display_quantity: number | null;
    display_unit: string | null;
  }>;
  instructions: string[];
}

export async function fetchExploreRecipeDetail(id: string): Promise<ExploreRecipeDetail> {
  const res = await authFetch(`/explore/recipe/${id}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function fetchExploreDeck(slot: SlotFilter = "any", count = 20): Promise<ExploreCard[]> {
  const qs = new URLSearchParams({ slot, count: String(count) }).toString();
  const res = await authFetch(`/explore/deck?${qs}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function swipeRecipe(
  public_recipe_id: string,
  direction: "like" | "skip",
): Promise<SwipeResult> {
  const res = await authFetch(`/explore/swipe`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ public_recipe_id, direction }),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function undoLastSwipe(): Promise<SwipeResult> {
  const res = await authFetch(`/explore/undo`, { method: "POST" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function fetchExploreStats(): Promise<ExploreStats> {
  const res = await authFetch(`/explore/stats`);
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
  source: "recipe" | "template" | "both";
  note: string | null;
}

export interface ShoppingListCategory {
  category: string;
  sort_index: number;
  items: ShoppingListItem[];
}

export interface ShoppingList {
  categories: ShoppingListCategory[];
  pantry_check: ShoppingListItem[];
  missing_recipes: string[];
}

// --- Household staples (pantry) ---

export interface StapleEntry {
  fdc_id: number;
  name: string;
  category: string;
}

export interface StaplesPayload {
  items: StapleEntry[];
  seeded_now: boolean;
}

export async function fetchStaples(): Promise<StaplesPayload> {
  const res = await authFetch(`/staples`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function addStaple(fdc_id: number): Promise<void> {
  const res = await authFetch(`/staples`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fdc_id }),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
}

export async function removeStaple(fdc_id: number): Promise<void> {
  const res = await authFetch(`/staples/${fdc_id}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) throw new Error(`${res.status} ${res.statusText}`);
}

export async function generateShoppingList(
  selections: { recipe_id: string; portions: number }[],
  includeTemplate: boolean = true,
): Promise<ShoppingList> {
  const qs = new URLSearchParams({ include_template: String(includeTemplate) }).toString();
  const res = await authFetch(`/shopping-lists/generate?${qs}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(selections),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

// --- Shopping list template (household baseline items) ---

export interface ShoppingTemplateItem {
  fdc_id: number;
  name: string;
  category: string;
  quantity_g: number;
  display_quantity: number;
  display_unit: string;
  note: string | null;
}

export async function fetchShoppingTemplate(): Promise<ShoppingTemplateItem[]> {
  const res = await authFetch(`/shopping-lists/template`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function upsertShoppingTemplateItem(
  fdc_id: number,
  quantity_g: number,
  note: string | null = null,
): Promise<ShoppingTemplateItem> {
  const res = await authFetch(`/shopping-lists/template`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fdc_id, quantity_g, note }),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function deleteShoppingTemplateItem(fdc_id: number): Promise<void> {
  const res = await authFetch(`/shopping-lists/template/${fdc_id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
}

export interface IngredientUnit {
  display_unit: string;
  grams_per_unit: number;
  round_step: number;
}

export async function fetchIngredientUnits(): Promise<Record<number, IngredientUnit>> {
  const res = await authFetch(`/shopping-lists/ingredient-units`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function fetchStoreLayout(): Promise<string[]> {
  const res = await authFetch(`/shopping-lists/store-layout`);
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
  const res = await authFetch(`/ingredients/usda-search?${qs}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function addToPantry(
  fdc_id: number,
  simple_name?: string,
  category?: string
): Promise<PantryEntry> {
  const res = await authFetch(`/pantry`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fdc_id, simple_name, category }),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function updateStoreLayout(categories: string[]): Promise<string[]> {
  const res = await authFetch(`/shopping-lists/store-layout`, {
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

// --- Flat calendar (the canonical model) -----------------------------------

export interface MealEntry {
  id: string;
  recipe_id: string;
  recipe_name: string | null;
  plan_date: string;             // ISO YYYY-MM-DD
  slot: "breakfast" | "lunch" | "dinner" | null;
  portions: number;
  image_path: string | null;
}

export async function fetchMeals(start: string, end: string): Promise<MealEntry[]> {
  const qs = new URLSearchParams({ start, end }).toString();
  const res = await authFetch(`/meals?${qs}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function createMeal(input: {
  recipe_id: string;
  plan_date: string;
  slot?: string | null;
  portions: number;
}): Promise<MealEntry> {
  const res = await authFetch(`/meals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function updateMeal(
  id: string,
  patch: { plan_date?: string; slot?: string | null; portions?: number },
): Promise<MealEntry> {
  const res = await authFetch(`/meals/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function deleteMeal(id: string): Promise<void> {
  const res = await authFetch(`/meals/${id}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) throw new Error(`${res.status} ${res.statusText}`);
}

export async function mealsShoppingList(
  start: string,
  end: string,
  includeTemplate: boolean = true,
): Promise<ShoppingList> {
  const qs = new URLSearchParams({
    start, end, include_template: String(includeTemplate),
  }).toString();
  const res = await authFetch(`/meals/shopping-list?${qs}`, { method: "POST" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
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
  const res = await authFetch(`/meal-plans`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function createMealPlan(
  name: string,
  start_date: string,
  entries: MealPlanEntryInput[] = []
): Promise<MealPlan> {
  const res = await authFetch(`/meal-plans`, {
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
  const res = await authFetch(`/meal-plans/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function deleteMealPlan(id: string): Promise<void> {
  const res = await authFetch(`/meal-plans/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
}

export interface SlotConfig {
  slot: string;                         // "breakfast" | "lunch" | "dinner"
  portions: number;                     // servings-sets per meal (>1 for batch cook)
  distinct_meals?: number | null;       // cap distinct dishes in this slot across the week
}

export interface GenerateMealPlanInput {
  prompt: string;
  start_date: string;
  days?: number;
  servings?: number;
  slot_configs: SlotConfig[];
  // Calendar entry_ids the user chose to overwrite in the pre-flight. Any other
  // already-occupied day is kept and skipped (never double-booked).
  replace_entry_ids?: string[];
}

export interface CalendarConflict {
  entry_id: string;
  plan_date: string;            // ISO YYYY-MM-DD
  slot: string;
  recipe_id: string | null;
  recipe_name: string | null;
  portions: number;
}

/** Meals already occupying the given slots in [start, end] (inclusive). The
 * week wizard calls this first to offer keep/replace per occupied day. */
export async function fetchCalendarConflicts(
  start: string,
  end: string,
  slots: string[],
): Promise<CalendarConflict[]> {
  const params = new URLSearchParams({ start, end });
  for (const s of slots) params.append("slots", s);
  const res = await authFetch(`/meal-plans/conflicts?${params.toString()}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

/** One progress event from the streaming /meal-plans/generate endpoint. */
export type GenerateEvent =
  | { type: "planning_start"; brief: string; days: number; slots: string[] }
  | { type: "planning_done"; meals_proposed: number; recipes_to_generate: number; plan_name: string }
  | { type: "recipe_start"; prompt: string; reason?: string }
  | { type: "recipe_done"; name: string; duration: number }
  | { type: "recipe_failed"; prompt: string; error: string }
  | { type: "persisting" }
  | { type: "complete"; plan: MealPlan; total_duration: number }
  | { type: "error"; message: string };

/**
 * Streams the meal-plan generator. Calls `onEvent` for every NDJSON event as
 * it arrives; resolves with the final saved plan from the `complete` event.
 * Throws if the stream ends without `complete`, or emits an `error` event.
 */
export async function generateMealPlan(
  input: GenerateMealPlanInput,
  onEvent: (event: GenerateEvent) => void,
): Promise<MealPlan> {
  const res = await authFetch(`/meal-plans/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });

  if (!res.ok) {
    let detail: string = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
    } catch { /* keep statusText */ }
    throw new Error(`${res.status} ${detail}`);
  }
  if (!res.body) throw new Error("No response body");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let plan: MealPlan | null = null;
  let lastError: string | null = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // NDJSON: events separated by \n
    let nl = buffer.indexOf("\n");
    while (nl >= 0) {
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (line) {
        try {
          const event = JSON.parse(line) as GenerateEvent;
          onEvent(event);
          if (event.type === "complete") plan = event.plan;
          if (event.type === "error") lastError = event.message;
        } catch {
          // Skip malformed line — backend should never emit one.
        }
      }
      nl = buffer.indexOf("\n");
    }
  }

  if (lastError) throw new Error(lastError);
  if (!plan) throw new Error("Generator finished without returning a plan");
  return plan;
}

/** Re-roll the flagged days of a saved plan, keeping the rest. Returns the
 * updated plan. The user flags only a few days, so this is a normal (non-stream)
 * request — show a spinner while it runs. */
export async function regenerateMealPlan(
  planId: string,
  flaggedEntryIds: string[],
  prompt: string,
  servings: number,
): Promise<MealPlan> {
  const res = await authFetch(`/meal-plans/${planId}/regenerate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ flagged_entry_ids: flaggedEntryIds, prompt, servings }),
  });
  if (!res.ok) {
    let detail: string = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
    } catch { /* keep statusText */ }
    throw new Error(`${res.status} ${detail}`);
  }
  return res.json();
}

export async function mealPlanShoppingList(id: string): Promise<ShoppingList> {
  const res = await authFetch(`/meal-plans/${id}/shopping-list`, { method: "POST" });
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

export interface ProposedAction {
  id: string;
  kind: string;
  summary: string;
  params: Record<string, unknown>;
}

export interface SendMessageResponse {
  reply: string;
  pending: ProposedAction[];
  session_id: string;
}

export interface ResolveResponse {
  id: string;
  status: "accepted" | "rejected" | "failed";
  result: string | null;
  created: Record<string, string> | null;
}

export async function acceptPending(id: string): Promise<ResolveResponse> {
  const res = await authFetch(`/chat/pending/${id}/accept`, { method: "POST" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function rejectPending(id: string): Promise<ResolveResponse> {
  const res = await authFetch(`/chat/pending/${id}/reject`, { method: "POST" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function listChatSessions(): Promise<ChatSessionSummary[]> {
  const res = await authFetch(`/chat/sessions`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function createChatSession(): Promise<ChatSessionDetail> {
  const res = await authFetch(`/chat/sessions`, { method: "POST" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function getChatSession(id: string): Promise<ChatSessionDetail> {
  const res = await authFetch(`/chat/sessions/${id}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function deleteChatSession(id: string): Promise<void> {
  const res = await authFetch(`/chat/sessions/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
}

// --- Household profile ---

export interface HouseholdProfile {
  family_size: number | null;
  dietary: string[];
  allergies: string[];
  dislikes: string[];
  likes: string[];
  typical_cook_time_min: number | null;
  batch_cook_preference: string | null;
  kitchen_equipment: string[];
  cuisines: string[];
  budget_level: string | null;
  notes: string[];
  visible_slots: string[];
  max_ingredients_to_buy: number | null;
  updated_at: string | null;
}

export type ProfilePatch = Partial<{
  family_size: number | null;
  dietary: string[];
  allergies: string[];
  dislikes: string[];
  likes: string[];
  typical_cook_time_min: number | null;
  batch_cook_preference: string | null;
  kitchen_equipment: string[];
  cuisines: string[];
  budget_level: string | null;
  notes: string[];
  visible_slots: string[];
  max_ingredients_to_buy: number | null;
  append_notes: string[];
}>;

export async function fetchProfile(): Promise<HouseholdProfile> {
  const res = await authFetch(`/profile`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function patchProfile(patch: ProfilePatch): Promise<HouseholdProfile> {
  const res = await authFetch(`/profile`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function resetProfile(): Promise<void> {
  const res = await authFetch(`/profile`, { method: "DELETE" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
}

export async function sendChatMessage(id: string, content: string): Promise<SendMessageResponse> {
  const res = await authFetch(`/chat/sessions/${id}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}
