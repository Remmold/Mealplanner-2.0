// Explore (recipe discovery) UI strings.
export const exploreEn = {
  heroTitle: "Explore",
  heroIntro:
    "Swipe through recipes from the starter library, fresh AI generations, and other households. Right to save, left to skip. Three likes in a cuisine and we'll quietly add it to your profile.",

  filterLabel: "Filter",
  filterAll: "All",

  stats: "♥ {{likes}} · ✕ {{skips}} · pool: {{pool}}",

  banner: {
    saved: "Saved ‘{{name}}’",
    addedCuisines: "Added {{cuisines}} to your cuisine preferences.",
    addToPlan: "Add to plan",
    dismiss: "Dismiss",
  },

  loadingDeck: "Loading deck…",
  emptyDeck:
    "The deck is empty for this filter. Try a different slot, or come back after a meal-plan generation fills the pool with fresh recipes.",

  // Drag-overlay decision labels.
  decisionSave: "SAVE",
  decisionSkip: "SKIP",

  loadingRecipe: "Loading recipe…",

  inspect: {
    ingredientsCount_one: "{{count}} ingredient",
    ingredientsCount_other: "{{count}} ingredients",
    ingredientsHeading: "Ingredients",
    instructionsHeading: "Instructions",
  },

  minutes: "{{count}} min",
  fdcFallback: "fdc {{id}}",

  // Card source badge.
  source: {
    starter: "starter",
    communityAi: "community AI",
    shared: "shared",
  },

  cardStats_one: "{{ingredients}} ingredients · {{count}} step",
  cardStats_other: "{{ingredients}} ingredients · {{count}} steps",
  ingredientsMore: " …+{{count}}",
  whyThis: "Why this",

  // Action-button titles & aria-labels.
  actions: {
    skipTitle: "Skip (←)",
    skipLabel: "Skip",
    undoTitle: "Undo last (↓)",
    undoLabel: "Undo last swipe",
    saveTitle: "Save (→)",
    saveLabel: "Save",
  },

  inspectCardLabel: "Inspect recipe",
  inspectCardTitle: "View full recipe",
};

export const exploreSv: typeof exploreEn = {
  heroTitle: "Utforska",
  heroIntro:
    "Svep genom recept från startbiblioteket, färska AI-genereringar och andra hushåll. Höger för att spara, vänster för att hoppa över. Tre gillningar inom ett kök så lägger vi tyst till det i din profil.",

  filterLabel: "Filter",
  filterAll: "Alla",

  stats: "♥ {{likes}} · ✕ {{skips}} · pool: {{pool}}",

  banner: {
    saved: "Sparade ‘{{name}}’",
    addedCuisines: "Lade till {{cuisines}} bland dina köksinställningar.",
    addToPlan: "Lägg till i planen",
    dismiss: "Avfärda",
  },

  loadingDeck: "Laddar kortlek…",
  emptyDeck:
    "Kortleken är tom för detta filter. Prova ett annat mål, eller kom tillbaka när en matsedelsgenerering fyllt poolen med nya recept.",

  decisionSave: "SPARA",
  decisionSkip: "HOPPA",

  loadingRecipe: "Laddar recept…",

  inspect: {
    ingredientsCount_one: "{{count}} ingrediens",
    ingredientsCount_other: "{{count}} ingredienser",
    ingredientsHeading: "Ingredienser",
    instructionsHeading: "Instruktioner",
  },

  minutes: "{{count}} min",
  fdcFallback: "fdc {{id}}",

  source: {
    starter: "start",
    communityAi: "community-AI",
    shared: "delat",
  },

  cardStats_one: "{{ingredients}} ingredienser · {{count}} steg",
  cardStats_other: "{{ingredients}} ingredienser · {{count}} steg",
  ingredientsMore: " …+{{count}}",
  whyThis: "Därför",

  actions: {
    skipTitle: "Hoppa över (←)",
    skipLabel: "Hoppa över",
    undoTitle: "Ångra senaste (↓)",
    undoLabel: "Ångra senaste svep",
    saveTitle: "Spara (→)",
    saveLabel: "Spara",
  },

  inspectCardLabel: "Granska recept",
  inspectCardTitle: "Visa hela receptet",
};
