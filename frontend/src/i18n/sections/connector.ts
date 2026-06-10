// OAuth consent screen — shown when an MCP client (Claude Code, etc.) connects
// to the household account and Supabase redirects here to ask the user to allow it.
export const connectorEn = {
  loading: "Loading authorization…",
  title: "Authorize access",
  intro: "{{client}} wants to connect to your Mealplanner account.",
  signedInAs: "Signed in as {{email}}",
  grants:
    "If you allow this, it can read your recipes, meal plan, pantry and profile, and propose changes — every change still needs your approval in the app.",
  redirectNote: "You'll be returned to {{host}}.",
  approve: "Authorize",
  deny: "Deny",
  working: "Working…",
  missingId: "This page was opened without an authorization request.",
  unknownClient: "An application",
};

export const connectorSv: typeof connectorEn = {
  loading: "Läser in behörighet…",
  title: "Godkänn åtkomst",
  intro: "{{client}} vill ansluta till ditt Mealplanner-konto.",
  signedInAs: "Inloggad som {{email}}",
  grants:
    "Om du tillåter detta kan appen läsa dina recept, din matsedel, ditt skafferi och din profil, och föreslå ändringar — varje ändring måste fortfarande godkännas i appen.",
  redirectNote: "Du skickas tillbaka till {{host}}.",
  approve: "Godkänn",
  deny: "Neka",
  working: "Arbetar…",
  missingId: "Den här sidan öppnades utan en behörighetsförfrågan.",
  unknownClient: "En applikation",
};
