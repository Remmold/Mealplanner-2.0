import { useEffect, useMemo, useState } from "react";
import type { ComponentType } from "react";
import { useTranslation } from "react-i18next";
import { BookOpen, CalendarDays, Compass, LogOut, ShoppingCart, Sparkles, Users } from "lucide-react";
import { onNavigate, dataChanged } from "./api";
import { LANG_STORAGE_KEY } from "./i18n";
import { useAuth } from "./auth/AuthProvider";
import SignIn from "./auth/SignIn";
import OAuthConsent from "./auth/OAuthConsent";
import CreateOrJoinHousehold from "./auth/CreateOrJoinHousehold";
import ProfileWizard from "./auth/ProfileWizard";
import WelcomeTour, { resetWelcomeTour, welcomeTourSeen } from "./tutorial/WelcomeTour";
import { fetchProfile } from "./lib/auth-api";
import PrivacyPolicy from "./legal/PrivacyPolicy";
import TermsOfService from "./legal/TermsOfService";
import { Button, Select } from "./components/ui";
import RecipeBuilder from "./components/RecipeBuilder";
import ShoppingList from "./components/ShoppingList";
import MealPlan, { type PlanIntent } from "./components/MealPlan";
import Chat from "./components/Chat";
import Profile from "./components/Profile";
import Explore from "./components/Explore";

type Tab = "plan" | "recipe" | "explore" | "shopping" | "profile";

// Meal Plan is the primary surface — it's where the value-prop starts
// (plan the week -> shopping list). Recipes is a supporting library.
// `labelKey` is a const i18n key so the typed t() accepts it directly.
const TABS = [
  { id: "plan",       labelKey: "nav.plan" },
  { id: "recipe",     labelKey: "nav.recipes" },
  { id: "explore",    labelKey: "nav.explore" },
  { id: "shopping",   labelKey: "nav.shopping" },
  { id: "profile",    labelKey: "nav.household" },
] as const satisfies { id: Tab; labelKey: string }[];

// Icons for the mobile bottom-nav (the desktop top-nav is text-only).
const TAB_ICONS: Record<Tab, ComponentType<{ size?: number }>> = {
  plan: CalendarDays,
  recipe: BookOpen,
  explore: Compass,
  shopping: ShoppingCart,
  profile: Users,
};

// URL ↔ tab mapping. Keep paths singular-noun-style to match the existing
// `recipe_id` deep link. Anything else falls through to "plan".
const PATH_TO_TAB: Record<string, Tab> = {
  "": "plan",
  "plan": "plan",
  "recipes": "recipe",
  "explore": "explore",
  "shopping": "shopping",
  "profile": "profile",
};

interface Route { tab: Tab; recipeId: string | null }

function parseRoute(pathname: string): Route {
  const seg = pathname.split("/").filter(Boolean);
  if (seg[0] === "recipes" && seg[1]) {
    return { tab: "recipe", recipeId: decodeURIComponent(seg[1]) };
  }
  const tab = PATH_TO_TAB[seg[0] ?? ""] ?? "plan";
  return { tab, recipeId: null };
}

function buildRoute(tab: Tab, recipeId: string | null): string {
  if (tab === "recipe") return recipeId ? `/recipes/${encodeURIComponent(recipeId)}` : "/recipes";
  if (tab === "plan") return "/plan";
  if (tab === "explore") return "/explore";
  if (tab === "shopping") return "/shopping";
  if (tab === "profile") return "/profile";
  return "/plan";
}

// The OAuth consent screen Supabase's OAuth 2.1 server redirects to during a
// "connector" login. It's not a tab and must bypass URL normalisation + the
// household/onboarding gates — it only needs a Supabase session.
function isConsentRoute(): boolean {
  return window.location.pathname.startsWith("/oauth/consent");
}

// Pull `/join/<token>` off the URL on mount. Returns null if the path is
// anything else. Mutates history so the token doesn't sit in the address bar.
function consumeJoinTokenFromUrl(): string | null {
  const match = /^\/join\/([^/?#]+)/.exec(window.location.pathname);
  if (match) {
    const token = decodeURIComponent(match[1]);
    window.history.replaceState({}, "", "/");
    // Stash it so the token survives a Google-OAuth round-trip (which returns
    // to "/" without the /join path) and the invite still applies after login.
    try { sessionStorage.setItem("pendingInviteToken", token); } catch { /* ignore */ }
    return token;
  }
  try { return sessionStorage.getItem("pendingInviteToken"); } catch { return null; }
}

function LoadingShell() {
  const { t } = useTranslation();
  return (
    <div className="auth-shell">
      <div className="brand auth-brand">
        <span className="brand-mark">Mealplanner</span>
        <span className="brand-tag">{t("nav.brandTag")}</span>
      </div>
      <p className="muted">{t("common.loading")}</p>
    </div>
  );
}

export default function App() {
  const { loading, session, me, signOut } = useAuth();
  const { t, i18n } = useTranslation();

  // Snapshot the join token at app mount; it's an auth gate, not a route.
  const initialJoinToken = useMemo(consumeJoinTokenFromUrl, []);
  const [pendingInviteToken, setPendingInviteToken] = useState<string | null>(initialJoinToken);

  // Initial tab + recipe come from the URL (so refresh / shared link works).
  // The join-token route is consumed upstream so it never reaches us here.
  const initialRoute = useMemo(() => parseRoute(window.location.pathname), []);
  const onConsentRoute = useMemo(isConsentRoute, []);
  const [tab, setTabRaw] = useState<Tab>(initialRoute.tab);
  // A one-shot plan intent (open the wizard / jump to a week) from a chat link
  // or accepted card. Lifted here because MealPlan only mounts on the plan tab,
  // so it can't be listening when the intent fires from another tab — we hand
  // it the intent as a prop and it consumes it on (re)render. See PlanIntent.
  const [planIntent, setPlanIntent] = useState<PlanIntent | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [initialRecipeId, setInitialRecipeId] = useState<string | null>(initialRoute.recipeId);
  // Whether the household profile is empty enough that the user should see
  // the ProfileWizard. We derive this from the server so a reset (or fresh
  // signup) re-triggers onboarding even if a stale localStorage flag from a
  // previous session said "done".
  // null = still checking, true = empty -> show wizard, false = filled or dismissed
  const [wizardNeeded, setWizardNeeded] = useState<boolean | null>(null);
  const [tourSeen, setTourSeen] = useState(welcomeTourSeen);
  const [legalOpen, setLegalOpen] = useState<"privacy" | "terms" | null>(null);

  // Normalise the URL on first paint so refreshes always land on /plan,
  // /recipes, etc. — not the bare "/" we may have started at.
  useEffect(() => {
    // The consent route owns its own URL (carries ?authorization_id=…); never
    // normalise it to a tab path.
    if (onConsentRoute) return;
    // Don't touch the URL if Supabase still needs to consume the auth hash
    // from a Google OAuth or magic-link redirect. replaceState would drop
    // the hash and the session would never establish.
    const hash = window.location.hash;
    if (hash.includes("access_token") || hash.includes("error_code") || hash.includes("provider_token")) {
      return;
    }
    const desired = buildRoute(initialRoute.tab, initialRoute.recipeId);
    if (window.location.pathname !== desired) {
      window.history.replaceState({}, "", desired);
    }
  }, []);

  // Single source of truth: state changes push history; back/forward pops
  // history and re-syncs state.
  function setTab(next: Tab, recipeId: string | null = null) {
    setTabRaw(next);
    if (recipeId !== null) setInitialRecipeId(recipeId);
    const path = buildRoute(next, recipeId);
    if (window.location.pathname !== path) {
      window.history.pushState({}, "", path);
    }
  }

  useEffect(() => {
    function onPop() {
      const r = parseRoute(window.location.pathname);
      setTabRaw(r.tab);
      if (r.recipeId) setInitialRecipeId(r.recipeId);
    }
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // Decide whether the profile wizard should fire. Fresh / reset profiles
  // (no family_size, no dietary, no cuisines, no allergies) are treated as
  // empty regardless of any localStorage flag from a past session.
  useEffect(() => {
    if (!session || !me?.household) { setWizardNeeded(null); return; }
    fetchProfile().then((p) => {
      const empty =
        !p.family_size
        && p.dietary.length === 0
        && p.cuisines.length === 0
        && p.allergies.length === 0
        && !p.typical_cook_time_min;
      setWizardNeeded(empty);
      // If we're (re)firing onboarding, also reset the welcome tour so the
      // user gets the full intro again.
      if (empty) {
        resetWelcomeTour();
        setTourSeen(false);
      }
    }).catch(() => setWizardNeeded(false));
  }, [session, me?.household]);

  useEffect(() => {
    return onNavigate((intent) => {
      if (intent.tab === "recipe") {
        setTab("recipe", intent.recipe_id ?? null);
      } else if (intent.tab === "plan") {
        setTab("plan");
        // Hand any open-wizard / jump-to-week flag to MealPlan as a prop; it
        // may not be mounted yet (we're switching to it now), so a listener
        // there would miss this. A fresh object guarantees the prop changes
        // even for a repeat intent (e.g. opening the wizard twice).
        if (intent.openGenerator || intent.week_start) {
          setPlanIntent({ openGenerator: intent.openGenerator, week_start: intent.week_start });
        }
      } else if (intent.tab === "shopping") {
        setTab("shopping");
      } else if (intent.tab === "profile") {
        setTab("profile");
      } else if (intent.tab === "explore") {
        setTab("explore");
      }
      // Keep chat open after a chat-link navigation — the user is mid-thought
      // and should be able to keep talking after landing on the destination.
    });
  }, []);

  // Default the UI language to the household's saved locale — but only until the
  // user makes an explicit per-device choice (which writes LANG_STORAGE_KEY).
  useEffect(() => {
    if (!me?.household) return;
    if (!localStorage.getItem(LANG_STORAGE_KEY)) {
      void i18n.changeLanguage(me.household.locale);
    }
  }, [me?.household, i18n]);

  // Recipe text is fetched per-locale, so a language switch must re-fetch it.
  // Broadcasting a data change makes the recipe/calendar views reload.
  useEffect(() => {
    const onLang = () => dataChanged("*");
    i18n.on("languageChanged", onLang);
    return () => i18n.off("languageChanged", onLang);
  }, [i18n]);

  if (loading) return <LoadingShell />;

  // OAuth "connector" consent screen: only needs a Supabase session, so it
  // short-circuits the household/profile/tour gates below. If not signed in,
  // send them through sign-in and back to this same consent URL.
  if (onConsentRoute) {
    if (!session) return <SignIn redirectTo={window.location.href} />;
    return <OAuthConsent />;
  }

  if (!session) return <SignIn />;
  if (!me) return <LoadingShell />;

  if (!me.household) {
    return (
      <CreateOrJoinHousehold
        pendingInviteToken={pendingInviteToken}
        onPendingTokenConsumed={() => {
          setPendingInviteToken(null);
          try { sessionStorage.removeItem("pendingInviteToken"); } catch { /* ignore */ }
        }}
      />
    );
  }

  // Wait until we've checked the profile before deciding whether to render
  // the wizard. Avoids a brief flash of the main app for fresh accounts.
  if (wizardNeeded === null) return <LoadingShell />;
  if (wizardNeeded) {
    return <ProfileWizard onComplete={() => setWizardNeeded(false)} />;
  }

  if (!tourSeen) {
    return <WelcomeTour open onClose={() => setTourSeen(true)} />;
  }

  return (
    <div className={"app-shell" + (chatOpen ? " app-shell-chat-open" : "")}>
      <header className="app-header">
        <div className="app-header-row">
          <div className="brand">
            <span className="brand-mark">Mealplanner</span>
            <span className="brand-tag">{t("nav.brandTag")}</span>
          </div>
          <nav className="nav">
            {TABS.map((tb) => (
              <button
                key={tb.id}
                onClick={() => setTab(tb.id)}
                className={`nav-btn ${tab === tb.id ? "active" : ""}`}
              >
                {t(tb.labelKey)}
              </button>
            ))}
          </nav>
          <div className="ml-auto auth-header-tail">
            {me.credit_balance !== null && (
              <span
                className={
                  "credit-pill" + (me.credit_balance <= 5 ? " credit-pill-low" : "")
                }
                title={
                  me.credit_balance <= 0
                    ? t("nav.creditsOut")
                    : t("nav.creditsTooltip", { balance: me.credit_balance.toFixed(1) })
                }
              >
                {t("nav.creditsRemaining", { balance: me.credit_balance.toFixed(1) })}
              </span>
            )}
            <Select
              value={i18n.language.startsWith("sv") ? "sv" : "en"}
              onChange={(v) => {
                localStorage.setItem(LANG_STORAGE_KEY, v);
                void i18n.changeLanguage(v);
              }}
              options={[
                { value: "en", label: "English" },
                { value: "sv", label: "Svenska" },
              ]}
              aria-label={t("nav.language")}
            />
            <Button variant="ghost" size="sm" onClick={signOut}>
              <LogOut size={14} />
              <span className="ml-1">{t("nav.signOut")}</span>
            </Button>
          </div>
        </div>
      </header>

      <main className="content">
        {tab === "recipe" && (
          <RecipeBuilder
            initialRecipeId={initialRecipeId}
            onInitialConsumed={() => setInitialRecipeId(null)}
          />
        )}
        {tab === "plan" && (
          <MealPlan pendingIntent={planIntent} onIntentConsumed={() => setPlanIntent(null)} />
        )}
        {tab === "explore" && <Explore />}
        {tab === "shopping" && <ShoppingList />}
        {tab === "profile" && <Profile />}
      </main>

      <footer className="app-footer">
        Mealplanner ·{" "}
        <button type="button" className="link-button" onClick={() => setLegalOpen("privacy")}>
          {t("nav.privacy")}
        </button>{" "}
        ·{" "}
        <button type="button" className="link-button" onClick={() => setLegalOpen("terms")}>
          {t("nav.terms")}
        </button>{" "}
        ·{" "}
        <button
          type="button"
          className="link-button"
          onClick={() => { resetWelcomeTour(); setTourSeen(false); }}
          title={t("nav.replayTour")}
        >
          {t("nav.replayTour")}
        </button>
      </footer>

      <nav className="mobile-nav">
        {TABS.map((tb) => {
          const Icon = TAB_ICONS[tb.id];
          return (
            <button
              key={tb.id}
              onClick={() => setTab(tb.id)}
              className={`mobile-nav-btn ${tab === tb.id ? "active" : ""}`}
            >
              <Icon size={20} />
              <span>{t(tb.labelKey)}</span>
            </button>
          );
        })}
      </nav>

      <PrivacyPolicy open={legalOpen === "privacy"} onClose={() => setLegalOpen(null)} />
      <TermsOfService open={legalOpen === "terms"} onClose={() => setLegalOpen(null)} />

      {!chatOpen && (
        <button onClick={() => setChatOpen(true)} className="chat-launcher" title={t("nav.openAssistant")}>
          <Sparkles size={24} />
        </button>
      )}
      <Chat open={chatOpen} onClose={() => setChatOpen(false)} />
    </div>
  );
}
