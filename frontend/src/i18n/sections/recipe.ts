// Recipe-builder UI strings.
export const recipeEn = {
  untitledRecipe: "Untitled Recipe",

  // Seeding starters
  seedNone: "No new starters added (you may already have them, or the corpus isn't built yet).",
  seedAdded_one: "Added {{count}} starter recipe.",
  seedAdded_other: "Added {{count}} starter recipes.",
  importStarters: "Import 12 starter recipes",
  importing: "Importing…",

  // Unsaved-changes guard
  discardConfirm: "You have unsaved changes. Discard them?",

  // Hero
  heroTitle: "Build a recipe",
  heroIntro: "Pick ingredients from your pantry, or describe a dish and let the kitchen think it up for you.",

  // Cookbook list
  cookbookTitle: "Your cookbook",
  newRecipe: "New recipe",
  noSavedRecipes: "No saved recipes yet.",
  chapterAll: "All",
  deleteRecipe: "Delete recipe",
  toBuyCount: "{{count}} to buy",
  stepCount_one: "{{count}} step",
  stepCount_other: "{{count}} steps",

  // Cookbook chapters
  chapters: {
    chicken: "Chicken",
    beef: "Beef",
    pork: "Pork",
    lamb: "Lamb",
    fish: "Fish",
    seafood: "Seafood",
    pasta: "Pasta",
    vegetarian: "Vegetarian",
  },

  // AI generation
  generateTitle: "Generate a recipe",
  generateHint: 'Try "Thai red curry for 4" or "quick weeknight pasta with what\'s in season"',
  generatePlaceholder: "What are we cooking?",
  thinking: "Thinking...",
  fromPhotos: "From photos",
  photosHint: "…or snap a photo of a recipe",
  readingPhotos: "Reading photos…",

  // Editor — top bar
  backToRecipes: "Back to recipes",
  generatingImage: "Generating image…",
  regenerateImage: "Regenerate image",
  regenerateImageTitle: "Generate a new image",

  // Editor — meta fields
  servings: "Servings",
  servingsCount_one: "{{count}} serving",
  servingsCount_other: "{{count}} servings",
  mealType: "Meal type",
  mealTypeAny: "— any —",
  create: "Create",
  startCooking: "Start cooking",
  startCookingTitle: "Open step-by-step cook mode",

  // Pantry picker
  pantry: "Pantry",
  findMore: "Find more",
  closeUsda: "Close USDA",
  usdaPlaceholder: "Search USDA — cod, feta, tahini...",
  usdaNoResults: "No results — press Search.",
  inPantry: "In pantry",
  allCategories: "All categories",
  filterByName: "Filter by name...",
  perHundredGram: "{{kcal}} kcal · {{protein}}g protein /100g",
  added: "Added",
  noIngredientsMatch: "No ingredients match.",

  // Current recipe
  ingredients: "Ingredients",
  pickIngredients: "Pick ingredients from your pantry.",
  grams: "g",
  alreadyInPantry: "Already in your pantry",
  pantryPillTitle: "{{grams}} g · click to remove",
  pantryItemGrams: "{{grams}}g",

  // Nutrition
  nutrition: "Nutrition",
  nutritionWeight: "Weight",
  nutritionEnergy: "Energy",
  nutritionProtein: "Protein",
  nutritionCarbs: "Carbs",
  nutritionSugars: "Sugars",
  nutritionFat: "Fat",
  nutritionSaturatedFat: "Saturated Fat",
  nutritionFiber: "Fiber",
  nutritionSalt: "Salt",
  nutritionMissing: "Missing data for some items.",

  // Instructions
  instructions: "Instructions",
  step: "Step",
  noStepsYet: "No steps yet — add one or generate a recipe.",
  removeStep: "Remove step",
};

export const recipeSv: typeof recipeEn = {
  untitledRecipe: "Namnlöst recept",

  // Seeding starters
  seedNone: "Inga nya startrecept lades till (du kanske redan har dem, eller så är korpusen inte byggd än).",
  seedAdded_one: "Lade till {{count}} startrecept.",
  seedAdded_other: "Lade till {{count}} startrecept.",
  importStarters: "Importera 12 startrecept",
  importing: "Importerar…",

  // Unsaved-changes guard
  discardConfirm: "Du har osparade ändringar. Kasta dem?",

  // Hero
  heroTitle: "Skapa ett recept",
  heroIntro: "Välj ingredienser från ditt skafferi, eller beskriv en rätt och låt köket hitta på den åt dig.",

  // Cookbook list
  cookbookTitle: "Din kokbok",
  newRecipe: "Nytt recept",
  noSavedRecipes: "Inga sparade recept än.",
  chapterAll: "Alla",
  deleteRecipe: "Ta bort recept",
  toBuyCount: "{{count}} att köpa",
  stepCount_one: "{{count}} steg",
  stepCount_other: "{{count}} steg",

  // Cookbook chapters
  chapters: {
    chicken: "Kyckling",
    beef: "Nötkött",
    pork: "Fläsk",
    lamb: "Lamm",
    fish: "Fisk",
    seafood: "Skaldjur",
    pasta: "Pasta",
    vegetarian: "Vegetariskt",
  },

  // AI generation
  generateTitle: "Generera ett recept",
  generateHint: 'Prova "Thailändsk röd curry för 4" eller "snabb vardagspasta med säsongens råvaror"',
  generatePlaceholder: "Vad ska vi laga?",
  thinking: "Tänker...",
  fromPhotos: "Från foton",
  photosHint: "…eller fota ett recept",
  readingPhotos: "Läser foton…",

  // Editor — top bar
  backToRecipes: "Tillbaka till recept",
  generatingImage: "Genererar bild…",
  regenerateImage: "Generera ny bild",
  regenerateImageTitle: "Generera en ny bild",

  // Editor — meta fields
  servings: "Portioner",
  servingsCount_one: "{{count}} portion",
  servingsCount_other: "{{count}} portioner",
  mealType: "Måltidstyp",
  mealTypeAny: "— valfri —",
  create: "Skapa",
  startCooking: "Börja laga",
  startCookingTitle: "Öppna steg-för-steg-läge",

  // Pantry picker
  pantry: "Skafferi",
  findMore: "Hitta fler",
  closeUsda: "Stäng USDA",
  usdaPlaceholder: "Sök i USDA — torsk, fetaost, tahini...",
  usdaNoResults: "Inga resultat — tryck på Sök.",
  inPantry: "I skafferiet",
  allCategories: "Alla kategorier",
  filterByName: "Filtrera på namn...",
  perHundredGram: "{{kcal}} kcal · {{protein}}g protein /100g",
  added: "Tillagd",
  noIngredientsMatch: "Inga ingredienser matchar.",

  // Current recipe
  ingredients: "Ingredienser",
  pickIngredients: "Välj ingredienser från ditt skafferi.",
  grams: "g",
  alreadyInPantry: "Finns redan i ditt skafferi",
  pantryPillTitle: "{{grams}} g · klicka för att ta bort",
  pantryItemGrams: "{{grams}}g",

  // Nutrition
  nutrition: "Näringsvärde",
  nutritionWeight: "Vikt",
  nutritionEnergy: "Energi",
  nutritionProtein: "Protein",
  nutritionCarbs: "Kolhydrater",
  nutritionSugars: "Socker",
  nutritionFat: "Fett",
  nutritionSaturatedFat: "Mättat fett",
  nutritionFiber: "Fiber",
  nutritionSalt: "Salt",
  nutritionMissing: "Saknar data för vissa varor.",

  // Instructions
  instructions: "Instruktioner",
  step: "Steg",
  noStepsYet: "Inga steg än — lägg till ett eller generera ett recept.",
  removeStep: "Ta bort steg",
};
