// Profile / household UI strings.
export const profileEn = {
  // List-field labels & placeholders (Tastes & constraints)
  dietaryLabel: "Dietary",
  dietaryPlaceholder: "vegetarian, pescatarian, gluten-free",
  allergiesLabel: "Allergies (strict)",
  allergiesPlaceholder: "peanuts, shellfish",
  dislikesLabel: "Dislikes",
  dislikesPlaceholder: "cilantro, liver",
  likesLabel: "Likes",
  likesPlaceholder: "bulgur, slow-roasted lamb",
  cuisinesLabel: "Cuisines",
  cuisinesPlaceholder: "Mediterranean, Thai, Scandi",
  kitchenEquipmentLabel: "Kitchen equipment",
  kitchenEquipmentPlaceholder: "oven, wok, pressure cooker",

  // Select empty option
  unset: "(unset)",

  // Loading / hero
  loading: "Loading...",
  heroTitle: "Your household",
  heroIntro:
    "The assistant uses this to personalise recipes and meal plans. You can edit it directly, or just chat — the assistant will pick things up and record them here on its own.",

  // Basics card
  basicsTitle: "Basics",
  familySize: "Family size",
  typicalCookTime: "Typical cook-time (min)",
  batchCookPreference: "Batch-cook preference",
  budget: "Budget",
  maxNonStapleIngredients: "Max non-staple ingredients",

  // Tastes & constraints card
  tastesTitle: "Tastes & constraints",
  tastesHint: "Comma-separated. Allergies are strict; the assistant never includes them.",

  // Actions
  saveProfile: "Save profile",
  resetEverything: "Reset everything",
  resetConfirm: "Clear everything the assistant knows about you?",

  // Notes card
  notesTitle: "Assistant notes",
  notesHint: "Observations the assistant has recorded (or you've added). Things that don't fit a field.",
  notesEmpty: "No notes yet — chat with the assistant and it'll learn.",
  removeNote: "Remove note",
  addNotePlaceholder: "Add a note...",
  noteButton: "Note",
  lastUpdated: "Last updated {{date}}",

  // Pantry section
  pantryTitle: "Pantry staples",
  pantryCount_one: "{{count}} item · always-have",
  pantryCount_other: "{{count}} items · always-have",
  pantryIntroBeforeEm: "These are silently omitted from shopping lists and shown under ",
  pantryIntroEm: "From your pantry",
  pantryIntroAfterEm:
    " in recipes. Uncheck things you've run out of. Use the chat (“we ran out of soy sauce”) for natural-language edits.",
  pantrySeeded: "Just seeded from the system list filtered by your cuisines.",
  pantryLoading: "Loading…",
  pantryEmpty: "No staples yet.",
  pantryRemoveTitle: "Click to remove from pantry",
};

export const profileSv: typeof profileEn = {
  // List-field labels & placeholders (Tastes & constraints)
  dietaryLabel: "Kost",
  dietaryPlaceholder: "vegetariskt, pescetariskt, glutenfritt",
  allergiesLabel: "Allergier (strikt)",
  allergiesPlaceholder: "jordnötter, skaldjur",
  dislikesLabel: "Ogillar",
  dislikesPlaceholder: "koriander, lever",
  likesLabel: "Gillar",
  likesPlaceholder: "bulgur, långbakad lammstek",
  cuisinesLabel: "Kök",
  cuisinesPlaceholder: "Medelhavet, thailändskt, skandinaviskt",
  kitchenEquipmentLabel: "Köksutrustning",
  kitchenEquipmentPlaceholder: "ugn, wok, tryckkokare",

  // Select empty option
  unset: "(ej angivet)",

  // Loading / hero
  loading: "Laddar...",
  heroTitle: "Ditt hushåll",
  heroIntro:
    "Assistenten använder detta för att anpassa recept och matsedlar. Du kan redigera det direkt, eller bara chatta — assistenten plockar upp saker och antecknar dem här på egen hand.",

  // Basics card
  basicsTitle: "Grunder",
  familySize: "Familjestorlek",
  typicalCookTime: "Typisk tillagningstid (min)",
  batchCookPreference: "Inställning för batchlagning",
  budget: "Budget",
  maxNonStapleIngredients: "Max antal ingredienser utöver skafferiet",

  // Tastes & constraints card
  tastesTitle: "Smaker & begränsningar",
  tastesHint: "Kommaseparerat. Allergier är strikta; assistenten tar aldrig med dem.",

  // Actions
  saveProfile: "Spara profil",
  resetEverything: "Återställ allt",
  resetConfirm: "Rensa allt som assistenten vet om dig?",

  // Notes card
  notesTitle: "Assistentens anteckningar",
  notesHint: "Observationer som assistenten har antecknat (eller du har lagt till). Saker som inte passar i ett fält.",
  notesEmpty: "Inga anteckningar än — chatta med assistenten så lär den sig.",
  removeNote: "Ta bort anteckning",
  addNotePlaceholder: "Lägg till en anteckning...",
  noteButton: "Anteckning",
  lastUpdated: "Senast uppdaterad {{date}}",

  // Pantry section
  pantryTitle: "Skafferivaror",
  pantryCount_one: "{{count}} vara · alltid hemma",
  pantryCount_other: "{{count}} varor · alltid hemma",
  pantryIntroBeforeEm: "Dessa utelämnas tyst från inköpslistor och visas under ",
  pantryIntroEm: "Från ditt skafferi",
  pantryIntroAfterEm:
    " i recept. Avmarkera sådant du har fått slut på. Använd chatten (”vi fick slut på soja”) för redigeringar på naturligt språk.",
  pantrySeeded: "Nyss förifylld från systemlistan filtrerad efter dina kök.",
  pantryLoading: "Laddar…",
  pantryEmpty: "Inga skafferivaror än.",
  pantryRemoveTitle: "Klicka för att ta bort från skafferiet",
};
