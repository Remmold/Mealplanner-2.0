// Swedish copy. Typed `Resources` so it must mirror en.ts exactly — a missing
// or misspelled key is a compile error. Best-effort translation; review welcome.
import type { Resources } from "./en";
import { mealplanSv } from "../sections/mealplan";
import { profileSv } from "../sections/profile";
import { shoppingTemplateSv } from "../sections/shoppingTemplate";
import { recipeSv } from "../sections/recipe";
import { shoppingSv } from "../sections/shopping";
import { exploreSv } from "../sections/explore";
import { chatSv } from "../sections/chat";
import { cookSv } from "../sections/cook";
import { signinSv } from "../sections/signin";
import { householdSv } from "../sections/household";
import { profileWizardSv } from "../sections/profileWizard";
import { tourSv } from "../sections/tour";
import { dateRangeSv } from "../sections/dateRange";
import { connectorSv } from "../sections/connector";

export const sv: Resources = {
  common: {
    save: "Spara",
    saving: "Sparar…",
    cancel: "Avbryt",
    close: "Stäng",
    delete: "Ta bort",
    edit: "Ändra",
    back: "Tillbaka",
    next: "Nästa",
    skip: "Hoppa över",
    add: "Lägg till",
    remove: "Ta bort",
    generate: "Skapa",
    generating: "Skapar…",
    search: "Sök",
    searching: "Söker…",
    done: "Klart",
    loading: "Läser in…",
    save_changes: "Spara ändringar",
  },

  nav: {
    plan: "Matsedel",
    recipes: "Recept",
    explore: "Utforska",
    shopping: "Inköp",
    household: "Hushåll",
    brandTag: "ditt kök, planerat",
    signOut: "Logga ut",
    creditsRemaining: "{{balance}} krediter",
    creditsOut: "Slut på krediter — återställs den 1:a",
    creditsTooltip: "{{balance}} AI-krediter kvar",
    language: "Språk",
    privacy: "Integritet",
    terms: "Villkor",
    replayTour: "Visa guiden igen",
    openAssistant: "Öppna assistenten",
  },

  enums: {
    slot: {
      breakfast: "Frukost",
      lunch: "Lunch",
      dinner: "Middag",
    },
    diet: {
      vegetarian: "vegetariskt",
      vegan: "veganskt",
      pescatarian: "pescetariskt",
      "gluten-free": "glutenfritt",
      "dairy-free": "mjölkfritt",
      "nut-free": "nötfritt",
      halal: "halal",
      kosher: "kosher",
    },
    cuisine: {
      Italian: "Italienskt",
      Thai: "Thailändskt",
      Mexican: "Mexikanskt",
      Indian: "Indiskt",
      Japanese: "Japanskt",
      Mediterranean: "Medelhavsmat",
      Chinese: "Kinesiskt",
      American: "Amerikanskt",
      French: "Franskt",
      "Middle Eastern": "Mellanöstern",
      Korean: "Koreanskt",
      Greek: "Grekiskt",
      Swedish: "Svenskt",
      Vietnamese: "Vietnamesiskt",
    },
    batch: {
      none: "Ingen",
      moderate: "Måttlig",
      heavy: "Mycket",
    },
    budget: {
      thrifty: "Sparsam",
      moderate: "Måttlig",
      splurge: "Lyxig",
    },
    category: {
      "Dairy & Eggs": "Mejeri & Ägg",
      "Meat & Poultry": "Kött & Fågel",
      "Fish & Seafood": "Fisk & Skaldjur",
      Vegetables: "Grönsaker",
      Fruits: "Frukt",
      Grains: "Spannmål",
      "Legumes & Nuts": "Baljväxter & Nötter",
      "Oils & Fats": "Oljor & Fetter",
      Other: "Övrigt",
      Protein: "Protein",
      "Sauces & Condiments": "Såser & Tillbehör",
      Seasonings: "Kryddor",
    },
  },

  units: {
    pcs: "st",
    piece: "st",
    clove: "klyfta",
    slice: "skiva",
    strip: "strimla",
    dl: "dl",
    msk: "msk",
    tsk: "tsk",
    kg: "kg",
    ml: "ml",
    g: "g",
  },

  mealplan: mealplanSv,
  profile: profileSv,
  shoppingTemplate: shoppingTemplateSv,
  recipe: recipeSv,
  shopping: shoppingSv,
  explore: exploreSv,
  chat: chatSv,
  cook: cookSv,
  signin: signinSv,
  household: householdSv,
  profileWizard: profileWizardSv,
  tour: tourSv,
  dateRange: dateRangeSv,
  connector: connectorSv,
};

export default sv;
