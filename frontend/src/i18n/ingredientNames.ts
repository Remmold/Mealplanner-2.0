// Runtime fdc_id -> Swedish ingredient name map. The names now live in Supabase
// (edited via the admin back-office), so we fetch them once after sign-in instead
// of shipping a build-time file. Until the fetch resolves, lookups miss and the
// caller falls back to the English name.
import { fetchIngredientSvNames } from "../lib/auth-api";

let svMap: Record<number, string> = {};
let loaded = false;

export async function loadIngredientNamesSv(): Promise<void> {
  if (loaded) return;
  try {
    svMap = await fetchIngredientSvNames();
    loaded = true;
  } catch {
    /* leave the map empty -> English fallback in useEnumLabels().ingredient() */
  }
}

export function ingredientNameSv(fdcId: number): string | undefined {
  return svMap[fdcId];
}
