// Typed wrappers around the auth-gated backend endpoints (/me, /households/*,
// /accounts/*). Every request through here auto-injects the user's Supabase
// JWT as a Bearer token. Existing api.ts (recipes, ingredients, etc.) stays
// untouched until step 2 of the real-product roadmap migrates those endpoints
// onto Postgres + RLS.

import { supabase } from "./supabase";

const BASE = "/api";

async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init.headers as Record<string, string> | undefined) ?? {}),
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  return fetch(`${BASE}${path}`, { ...init, headers });
}

async function ok<T>(res: Response, ctx: string): Promise<T> {
  if (!res.ok) {
    let detail: string | undefined;
    try {
      const body = (await res.json()) as { detail?: string };
      detail = body?.detail;
    } catch {
      /* response had no JSON body */
    }
    throw new Error(detail ?? `${ctx} failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

// ---- Types ------------------------------------------------------------------

export type Locale = "en" | "sv";
export type HouseholdRole = "owner" | "member";

export interface HouseholdInfo {
  id: string;
  name: string;
  role: HouseholdRole;
  locale: Locale;
  member_count: number;
}

export interface MeResponse {
  user_id: string;
  email: string | null;
  household: HouseholdInfo | null;
  credit_balance: number | null;
  is_admin: boolean;
}

export interface InviteResponse {
  token: string;
  expires_at: string;
  join_url: string;
}

// ---- Endpoints --------------------------------------------------------------

export async function fetchMe(): Promise<MeResponse> {
  return ok<MeResponse>(await authFetch("/me"), "/me");
}

export async function createHousehold(
  name: string,
  locale: Locale = "en",
): Promise<HouseholdInfo> {
  return ok<HouseholdInfo>(
    await authFetch("/households", {
      method: "POST",
      body: JSON.stringify({ name, locale }),
    }),
    "create household",
  );
}

export async function joinHouseholdByToken(
  token: string,
  locale: Locale = "en",
): Promise<HouseholdInfo> {
  return ok<HouseholdInfo>(
    await authFetch(`/households/join/${encodeURIComponent(token)}`, {
      method: "POST",
      body: JSON.stringify({ locale }),
    }),
    "join household",
  );
}

export async function createInvite(householdId: string): Promise<InviteResponse> {
  return ok<InviteResponse>(
    await authFetch(`/households/${encodeURIComponent(householdId)}/invites`, {
      method: "POST",
    }),
    "create invite",
  );
}

// Self-leave (user_id = own id) or owner-kick. After a self-leave the caller
// has no household, so App.tsx routes them back to the create/join screen.
export async function leaveHousehold(householdId: string, userId: string): Promise<void> {
  const res = await authFetch(
    `/households/${encodeURIComponent(householdId)}/members/${encodeURIComponent(userId)}`,
    { method: "DELETE" },
  );
  if (!res.ok && res.status !== 204) {
    let detail: string | undefined;
    try { detail = ((await res.json()) as { detail?: string }).detail; } catch { /* no body */ }
    throw new Error(detail ?? `leave household failed (${res.status})`);
  }
}

export async function deleteAccount(): Promise<void> {
  const res = await authFetch("/accounts/me", { method: "DELETE" });
  if (!res.ok && res.status !== 204) {
    throw new Error(`delete account failed (${res.status})`);
  }
}

// ---- Admin (server-gated to ADMIN_USER_IDS; non-admins get 403) -------------

export interface AdminLocaleContent {
  name: string;
  instructions: string[];
}

export interface AdminRecipeTranslation {
  id: string;
  base_name: string;
  en: AdminLocaleContent;
  sv: AdminLocaleContent;
}

export async function fetchAdminRecipes(): Promise<AdminRecipeTranslation[]> {
  return ok<AdminRecipeTranslation[]>(await authFetch("/admin/recipes"), "admin recipes");
}

export async function saveAdminRecipeTranslations(
  id: string,
  en: AdminLocaleContent,
  sv: AdminLocaleContent,
): Promise<void> {
  await ok<unknown>(
    await authFetch(`/admin/recipes/${encodeURIComponent(id)}/translations`, {
      method: "PUT",
      body: JSON.stringify({ en, sv }),
    }),
    "save translations",
  );
}

export async function reloadCatalog(): Promise<{ ok: boolean; pantry: number }> {
  return ok<{ ok: boolean; pantry: number }>(
    await authFetch("/admin/reload-catalog", { method: "POST" }),
    "reload catalog",
  );
}

// Ingredient names: the Swedish map (loaded once by every client) + the admin editor.
export async function fetchIngredientSvNames(): Promise<Record<number, string>> {
  return ok<Record<number, string>>(await authFetch("/ingredients/sv-names"), "sv names");
}

export interface AdminIngredient {
  fdc_id: number;
  simple_name: string;
  name_sv: string | null;
  category: string;
  subcategory: string | null;
}

export async function fetchAdminIngredients(q: string): Promise<AdminIngredient[]> {
  const qs = new URLSearchParams({ q, limit: "100" }).toString();
  return ok<AdminIngredient[]>(await authFetch(`/admin/ingredients?${qs}`), "admin ingredients");
}

export async function saveAdminIngredient(
  fdc_id: number,
  body: { simple_name: string; name_sv: string | null },
): Promise<void> {
  await ok<unknown>(
    await authFetch(`/admin/ingredients/${fdc_id}`, { method: "PUT", body: JSON.stringify(body) }),
    "save ingredient",
  );
}

// ---- Profile (subset used by the onboarding wizard) ------------------------

export interface ProfilePatch {
  family_size?: number | null;
  dietary?: string[];
  allergies?: string[];
  cuisines?: string[];
  typical_cook_time_min?: number | null;
}

export async function patchProfile(body: ProfilePatch): Promise<unknown> {
  return ok<unknown>(
    await authFetch("/profile", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
    "patch profile",
  );
}

// What we actually surface in UI — minimal subset. The backend returns
// more fields but the meal-plan generator only needs these to build the
// "Mealplanner will use this context" hint.
export interface ProfileSummary {
  family_size: number | null;
  dietary: string[];
  allergies: string[];
  cuisines: string[];
  typical_cook_time_min: number | null;
  batch_cook_preference: string | null;
  notes: string[];
  visible_slots: string[];   // [] = all three slots; otherwise a subset of breakfast/lunch/dinner
}

export async function fetchProfile(): Promise<ProfileSummary> {
  return ok<ProfileSummary>(await authFetch("/profile"), "fetch profile");
}
