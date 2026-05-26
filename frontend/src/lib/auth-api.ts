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

export async function deleteAccount(): Promise<void> {
  const res = await authFetch("/accounts/me", { method: "DELETE" });
  if (!res.ok && res.status !== 204) {
    throw new Error(`delete account failed (${res.status})`);
  }
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
