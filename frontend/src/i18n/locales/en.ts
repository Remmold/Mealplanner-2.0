// English copy — the source of truth for every UI string. `sv.ts` must mirror
// this shape exactly (it's typed `Resources`, so a missing key fails the build).
// Keys are grouped by domain; interpolation uses {{var}}, plurals use the
// i18next `_one`/`_other` suffixes with a `count` option.
//
// Per-component strings live in ./sections/* (one file per component, each
// exporting <domain>En + <domain>Sv) and are composed in below.
import { mealplanEn } from "../sections/mealplan";
import { profileEn } from "../sections/profile";
import { shoppingTemplateEn } from "../sections/shoppingTemplate";
import { recipeEn } from "../sections/recipe";
import { shoppingEn } from "../sections/shopping";
import { exploreEn } from "../sections/explore";
import { chatEn } from "../sections/chat";
import { cookEn } from "../sections/cook";
import { signinEn } from "../sections/signin";
import { householdEn } from "../sections/household";
import { profileWizardEn } from "../sections/profileWizard";
import { tourEn } from "../sections/tour";
import { dateRangeEn } from "../sections/dateRange";
import { connectorEn } from "../sections/connector";

export const en = {
  common: {
    save: "Save",
    saving: "Saving…",
    cancel: "Cancel",
    close: "Close",
    delete: "Delete",
    edit: "Edit",
    back: "Back",
    next: "Next",
    skip: "Skip",
    add: "Add",
    remove: "Remove",
    generate: "Generate",
    generating: "Generating…",
    search: "Search",
    searching: "Searching…",
    done: "Done",
    loading: "Loading…",
    save_changes: "Save changes",
  },

  nav: {
    plan: "Meal Plan",
    recipes: "Recipes",
    explore: "Explore",
    shopping: "Shopping",
    household: "Household",
    brandTag: "your kitchen, planned",
    signOut: "Sign out",
    creditsRemaining: "{{balance}} credits",
    creditsOut: "Out of credits — resets on the 1st",
    creditsTooltip: "{{balance}} AI credits remaining",
    language: "Language",
    privacy: "Privacy",
    terms: "Terms",
    replayTour: "Replay tour",
    openAssistant: "Open assistant",
  },

  enums: {
    slot: {
      breakfast: "Breakfast",
      lunch: "Lunch",
      dinner: "Dinner",
    },
    diet: {
      vegetarian: "vegetarian",
      vegan: "vegan",
      pescatarian: "pescatarian",
      "gluten-free": "gluten-free",
      "dairy-free": "dairy-free",
      "nut-free": "nut-free",
      halal: "halal",
      kosher: "kosher",
    },
    cuisine: {
      Italian: "Italian",
      Thai: "Thai",
      Mexican: "Mexican",
      Indian: "Indian",
      Japanese: "Japanese",
      Mediterranean: "Mediterranean",
      Chinese: "Chinese",
      American: "American",
      French: "French",
      "Middle Eastern": "Middle Eastern",
      Korean: "Korean",
      Greek: "Greek",
      Swedish: "Swedish",
      Vietnamese: "Vietnamese",
    },
    batch: {
      none: "None",
      moderate: "Moderate",
      heavy: "Heavy",
    },
    budget: {
      thrifty: "Thrifty",
      moderate: "Moderate",
      splurge: "Splurge",
    },
    category: {
      "Dairy & Eggs": "Dairy & Eggs",
      "Meat & Poultry": "Meat & Poultry",
      "Fish & Seafood": "Fish & Seafood",
      Vegetables: "Vegetables",
      Fruits: "Fruits",
      Grains: "Grains",
      "Legumes & Nuts": "Legumes & Nuts",
      "Oils & Fats": "Oils & Fats",
      Other: "Other",
      Protein: "Protein",
      "Sauces & Condiments": "Sauces & Condiments",
      Seasonings: "Seasonings",
    },
  },

  // Shopping/recipe quantity units. Keyed by the raw display_unit string.
  units: {
    pcs: "pcs",
    piece: "pc",
    clove: "clove",
    slice: "slice",
    strip: "strip",
    dl: "dl",
    msk: "tbsp",
    tsk: "tsp",
    kg: "kg",
    ml: "ml",
    g: "g",
  },

  mealplan: mealplanEn,
  profile: profileEn,
  shoppingTemplate: shoppingTemplateEn,
  recipe: recipeEn,
  shopping: shoppingEn,
  explore: exploreEn,
  chat: chatEn,
  cook: cookEn,
  signin: signinEn,
  household: householdEn,
  profileWizard: profileWizardEn,
  tour: tourEn,
  dateRange: dateRangeEn,
  connector: connectorEn,
};

export default en;
export type Resources = typeof en;
