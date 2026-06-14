// Localized display labels for enum VALUES that stay English in data/logic
// (slots, diet, cuisines, batch/budget levels, shopping categories). Components
// keep storing/sending the English identifier; they only render through these.
//
// Each map is `as const` so the looked-up value is a string-literal key the
// typed t() accepts; unknown values (e.g. a user-renamed store category) fall
// back to the raw string.
import { useTranslation } from "react-i18next";
import { ingredientNameSv } from "./ingredientNames";

const SLOT = {
  breakfast: "enums.slot.breakfast",
  lunch: "enums.slot.lunch",
  dinner: "enums.slot.dinner",
} as const;

const DIET = {
  vegetarian: "enums.diet.vegetarian",
  vegan: "enums.diet.vegan",
  pescatarian: "enums.diet.pescatarian",
  "gluten-free": "enums.diet.gluten-free",
  "dairy-free": "enums.diet.dairy-free",
  "nut-free": "enums.diet.nut-free",
  halal: "enums.diet.halal",
  kosher: "enums.diet.kosher",
} as const;

const CUISINE = {
  Italian: "enums.cuisine.Italian",
  Thai: "enums.cuisine.Thai",
  Mexican: "enums.cuisine.Mexican",
  Indian: "enums.cuisine.Indian",
  Japanese: "enums.cuisine.Japanese",
  Mediterranean: "enums.cuisine.Mediterranean",
  Chinese: "enums.cuisine.Chinese",
  American: "enums.cuisine.American",
  French: "enums.cuisine.French",
  "Middle Eastern": "enums.cuisine.Middle Eastern",
  Korean: "enums.cuisine.Korean",
  Greek: "enums.cuisine.Greek",
  Swedish: "enums.cuisine.Swedish",
  Vietnamese: "enums.cuisine.Vietnamese",
} as const;

const BATCH = {
  none: "enums.batch.none",
  moderate: "enums.batch.moderate",
  heavy: "enums.batch.heavy",
} as const;

const BUDGET = {
  thrifty: "enums.budget.thrifty",
  moderate: "enums.budget.moderate",
  splurge: "enums.budget.splurge",
} as const;

const UNIT = {
  pcs: "units.pcs",
  piece: "units.piece",
  clove: "units.clove",
  slice: "units.slice",
  strip: "units.strip",
  dl: "units.dl",
  msk: "units.msk",
  tsk: "units.tsk",
  kg: "units.kg",
  ml: "units.ml",
  g: "units.g",
} as const;

const CATEGORY = {
  "Dairy & Eggs": "enums.category.Dairy & Eggs",
  "Meat & Poultry": "enums.category.Meat & Poultry",
  "Fish & Seafood": "enums.category.Fish & Seafood",
  Vegetables: "enums.category.Vegetables",
  Fruits: "enums.category.Fruits",
  Grains: "enums.category.Grains",
  "Legumes & Nuts": "enums.category.Legumes & Nuts",
  "Oils & Fats": "enums.category.Oils & Fats",
  Other: "enums.category.Other",
  Protein: "enums.category.Protein",
  "Sauces & Condiments": "enums.category.Sauces & Condiments",
  Seasonings: "enums.category.Seasonings",
} as const;

const capitalize = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

export function useEnumLabels() {
  const { t, i18n } = useTranslation();
  const isSv = i18n.language.startsWith("sv");
  return {
    // Quantity unit (e.g. "pcs" -> "st"); raw string for unknown units.
    unit: (v?: string | null) => {
      const k = v ? UNIT[v as keyof typeof UNIT] : undefined;
      return k ? t(k) : v ?? "";
    },
    // Ingredient display name. USDA names are English; for Swedish we map the
    // item's fdc_id to a Swedish base name (capitalized), falling back to the
    // English name passed in when the id isn't in the alias-derived map.
    ingredient: (fdcId?: number | null, fallback?: string | null) => {
      if (isSv && fdcId != null) {
        const sv = ingredientNameSv(fdcId);
        if (sv) return capitalize(sv);
      }
      return fallback ?? "";
    },
    slot: (v?: string | null) => {
      const k = v ? SLOT[v as keyof typeof SLOT] : undefined;
      return k ? t(k) : v ?? "";
    },
    diet: (v?: string | null) => {
      const k = v ? DIET[v as keyof typeof DIET] : undefined;
      return k ? t(k) : v ?? "";
    },
    cuisine: (v?: string | null) => {
      const k = v ? CUISINE[v as keyof typeof CUISINE] : undefined;
      return k ? t(k) : v ?? "";
    },
    batch: (v?: string | null) => {
      const k = v ? BATCH[v as keyof typeof BATCH] : undefined;
      return k ? t(k) : v ?? "";
    },
    budget: (v?: string | null) => {
      const k = v ? BUDGET[v as keyof typeof BUDGET] : undefined;
      return k ? t(k) : v ?? "";
    },
    category: (v?: string | null) => {
      const k = v ? CATEGORY[v as keyof typeof CATEGORY] : undefined;
      return k ? t(k) : v ?? "";
    },
  };
}
