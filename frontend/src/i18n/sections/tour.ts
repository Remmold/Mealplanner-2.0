// Welcome-tour strings.
export const tourEn = {
  brandTag: "your kitchen, planned",

  steps: {
    plan: {
      title: "Plan your week",
      body:
        "Mealplanner turns a sentence (\"easy vegetarian week, batch-cook two dinners\") "
        + "into a full meal plan — generated, scaled, and respectful of your "
        + "household's dietary preferences.",
    },
    cook: {
      title: "Cook from real recipes",
      body:
        "Each meal lands as a real recipe — ingredients with quantities, "
        + "step-by-step instructions, USDA-backed nutrition. Tap a step to start "
        + "a timer; scale servings on the fly.",
    },
    shop: {
      title: "One trip, one list",
      body:
        "Your plan becomes a single shopping list: ingredients summed across "
        + "the week, converted to shopping units (eggs, dl, cloves), and ordered "
        + "by your store's aisle layout. No mental math.",
    },
  },

  getStarted: "Got it — let's start",
  skipTour: "Skip tour",
};

export const tourSv: typeof tourEn = {
  brandTag: "ditt kök, planerat",

  steps: {
    plan: {
      title: "Planera din vecka",
      body:
        "Mealplanner förvandlar en mening (\"enkel vegetarisk vecka, satskoka två "
        + "middagar\") till en komplett matsedel — skapad, skalad och anpassad "
        + "efter hushållets kostpreferenser.",
    },
    cook: {
      title: "Laga riktiga recept",
      body:
        "Varje måltid blir ett riktigt recept — ingredienser med mängder, "
        + "steg-för-steg-instruktioner och USDA-baserad näring. Tryck på ett steg "
        + "för att starta en timer; skala portioner i farten.",
    },
    shop: {
      title: "En tur, en lista",
      body:
        "Din plan blir en enda inköpslista: ingredienser summerade över veckan, "
        + "omräknade till inköpsenheter (ägg, dl, klyftor) och sorterade efter "
        + "din butiks hyllordning. Inget huvudräknande.",
    },
  },

  getStarted: "Klart — nu börjar vi",
  skipTour: "Hoppa över guiden",
};
