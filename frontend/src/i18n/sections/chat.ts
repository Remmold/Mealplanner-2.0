// Chat assistant UI chrome strings.
export const chatEn = {
  header: {
    title: "Mealplanner assistant",
    sessions: "Sessions",
    newChat: "New",
  },

  sessions: {
    empty: "No previous chats.",
    deleteChat: "Delete chat",
    messageCount_one: "{{count}} message",
    messageCount_other: "{{count}} messages",
  },

  welcome: {
    greeting: "Hi there",
    intro: "I can manage your recipes, plans and pantry. Try:",
    // Each suggestion has a `prompt` (sent to the assistant when clicked) and a
    // shorter `label` (shown in the list).
    suggestions: {
      vegetarianWeekPrompt: "Create a vegetarian week starting next Monday for 4 people",
      vegetarianWeekLabel: '"Create a vegetarian week starting next Monday for 4 people"',
      addCurryPrompt: "Add Thai red curry to Wednesday dinner in my current plan",
      addCurryLabel: '"Add Thai red curry to Wednesday dinner"',
      quickPastaPrompt: "Generate a quick weeknight pasta and save it",
      quickPastaLabel: '"Generate a quick weeknight pasta and save it"',
      savedRecipesPrompt: "Show me my saved recipes",
      savedRecipesLabel: '"Show me my saved recipes"',
    },
  },

  pending: {
    header_one: "{{count}} proposed action",
    header_other: "{{count}} proposed actions",
    acceptAll: "Accept all",
    reject: "Reject",
    accept: "Accept",
    applying: "Applying…",
    rejecting: "Rejecting…",
    rejected: "Rejected",
    imageGenerating: "Image is generating…",
    previewMeta_one: "{{servings}} servings · {{toBuy}} to buy · {{steps}} step",
    previewMeta_other: "{{servings}} servings · {{toBuy}} to buy · {{steps}} steps",
    view: "View",
    // Friendly category tag on each proposal card, keyed by the kind's domain
    // (recipe.* / calendar.* / profile.* / pantry.* / plan.*).
    kinds: {
      recipe: "Recipe",
      calendar: "Calendar",
      profile: "Preference",
      pantry: "Pantry",
      plan: "Plan",
    },
  },

  progress: {
    heading: "Applying actions",
    allDone: "All done.",
    working: "The assistant is working — leave this open until it finishes.",
  },

  // Fallback status text shown when the server returns no result message.
  failed: "Failed",

  input: {
    placeholder: "Ask the assistant…",
    send: "Send",
  },
};

export const chatSv: typeof chatEn = {
  header: {
    title: "Mealplanner-assistenten",
    sessions: "Sessioner",
    newChat: "Ny",
  },

  sessions: {
    empty: "Inga tidigare chattar.",
    deleteChat: "Ta bort chatt",
    messageCount_one: "{{count}} meddelande",
    messageCount_other: "{{count}} meddelanden",
  },

  welcome: {
    greeting: "Hej där",
    intro: "Jag kan sköta dina recept, planer och skafferi. Prova:",
    suggestions: {
      vegetarianWeekPrompt: "Skapa en vegetarisk vecka som börjar nästa måndag för 4 personer",
      vegetarianWeekLabel: '"Skapa en vegetarisk vecka som börjar nästa måndag för 4 personer"',
      addCurryPrompt: "Lägg till thailändsk röd curry till onsdagens middag i min nuvarande plan",
      addCurryLabel: '"Lägg till thailändsk röd curry till onsdagens middag"',
      quickPastaPrompt: "Skapa en snabb vardagspasta och spara den",
      quickPastaLabel: '"Skapa en snabb vardagspasta och spara den"',
      savedRecipesPrompt: "Visa mina sparade recept",
      savedRecipesLabel: '"Visa mina sparade recept"',
    },
  },

  pending: {
    header_one: "{{count}} föreslagen åtgärd",
    header_other: "{{count}} föreslagna åtgärder",
    acceptAll: "Acceptera alla",
    reject: "Avvisa",
    accept: "Acceptera",
    applying: "Tillämpar…",
    rejecting: "Avvisar…",
    rejected: "Avvisad",
    imageGenerating: "Bilden skapas…",
    previewMeta_one: "{{servings}} portioner · {{toBuy}} att köpa · {{steps}} steg",
    previewMeta_other: "{{servings}} portioner · {{toBuy}} att köpa · {{steps}} steg",
    view: "Visa",
    kinds: {
      recipe: "Recept",
      calendar: "Kalender",
      profile: "Inställning",
      pantry: "Skafferi",
      plan: "Plan",
    },
  },

  progress: {
    heading: "Tillämpar åtgärder",
    allDone: "Allt klart.",
    working: "Assistenten arbetar — låt detta vara öppet tills den är klar.",
  },

  failed: "Misslyckades",

  input: {
    placeholder: "Fråga assistenten…",
    send: "Skicka",
  },
};
