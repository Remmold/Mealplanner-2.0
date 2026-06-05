import { useEffect, useMemo, useState } from "react";
import { LogOut, Sparkles } from "lucide-react";
import { onNavigate } from "./api";
import { useAuth } from "./auth/AuthProvider";
import SignIn from "./auth/SignIn";
import CreateOrJoinHousehold from "./auth/CreateOrJoinHousehold";
import ProfileWizard from "./auth/ProfileWizard";
import WelcomeTour, { resetWelcomeTour, welcomeTourSeen } from "./tutorial/WelcomeTour";
import { fetchProfile } from "./lib/auth-api";
import PrivacyPolicy from "./legal/PrivacyPolicy";
import TermsOfService from "./legal/TermsOfService";
import { Button } from "./components/ui";
import RecipeBuilder from "./components/RecipeBuilder";
import ShoppingList from "./components/ShoppingList";
import MealPlan from "./components/MealPlan";
import Chat from "./components/Chat";
import Profile from "./components/Profile";
import Explore from "./components/Explore";

type Tab = "plan" | "recipe" | "explore" | "shopping" | "profile";

// Meal Plan is the primary surface — it's where the value-prop starts
// (plan the week -> shopping list). Recipes is a supporting library.
const TABS: { id: Tab; label: string }[] = [
  { id: "plan",       label: "Meal Plan" },
  { id: "recipe",     label: "Recipes" },
  { id: "explore",    label: "Explore" },
  { id: "shopping",   label: "Shopping" },
  { id: "profile",    label: "Household" },
];

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

// Pull `/join/<token>` off the URL on mount. Returns null if the path is
// anything else. Mutates history so the token doesn't sit in the address bar.
function consumeJoinTokenFromUrl(): string | null {
  const match = /^\/join\/([^/?#]+)/.exec(window.location.pathname);
  if (!match) return null;
  const token = decodeURIComponent(match[1]);
  window.history.replaceState({}, "", "/");
  return token;
}

function LoadingShell() {
  return (
    <div className="auth-shell">
      <div className="brand auth-brand">
        <span className="brand-mark">Hearth</span>
        <span className="brand-tag">your kitchen, planned</span>
      </div>
      <p className="muted">Loading…</p>
    </div>
  );
}

export default function App() {
  const { loading, session, me, signOut } = useAuth();

  // Snapshot the join token at app mount; it's an auth gate, not a route.
  const initialJoinToken = useMemo(consumeJoinTokenFromUrl, []);
  const [pendingInviteToken, setPendingInviteToken] = useState<string | null>(initialJoinToken);

  // Initial tab + recipe come from the URL (so refresh / shared link works).
  // The join-token route is consumed upstream so it never reaches us here.
  const initialRoute = useMemo(() => parseRoute(window.location.pathname), []);
  const [tab, setTabRaw] = useState<Tab>(initialRoute.tab);
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
        // The `openGenerator` flag is handled by MealPlan's own listener.
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

  if (loading) return <LoadingShell />;
  if (!session) return <SignIn />;
  if (!me) return <LoadingShell />;

  if (!me.household) {
    return (
      <CreateOrJoinHousehold
        pendingInviteToken={pendingInviteToken}
        onPendingTokenConsumed={() => setPendingInviteToken(null)}
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
            <span className="brand-mark">Hearth</span>
            <span className="brand-tag">your kitchen, planned</span>
          </div>
          <nav className="nav">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`nav-btn ${tab === t.id ? "active" : ""}`}
              >
                {t.label}
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
                    ? "Out of credits — resets on the 1st"
                    : `${me.credit_balance.toFixed(1)} AI credits remaining`
                }
              >
                {me.credit_balance.toFixed(1)} credits
              </span>
            )}
            <Button variant="ghost" size="sm" onClick={signOut}>
              <LogOut size={14} />
              <span className="ml-1">Sign out</span>
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
        {tab === "plan" && <MealPlan />}
        {tab === "explore" && <Explore />}
        {tab === "shopping" && <ShoppingList />}
        {tab === "profile" && <Profile />}
      </main>

      <footer className="app-footer">
        Hearth · Mealplanner 2.0 ·{" "}
        <button type="button" className="link-button" onClick={() => setLegalOpen("privacy")}>
          Privacy
        </button>{" "}
        ·{" "}
        <button type="button" className="link-button" onClick={() => setLegalOpen("terms")}>
          Terms
        </button>{" "}
        ·{" "}
        <button
          type="button"
          className="link-button"
          onClick={() => { resetWelcomeTour(); setTourSeen(false); }}
          title="Replay the welcome tour"
        >
          Replay tour
        </button>
      </footer>

      <PrivacyPolicy open={legalOpen === "privacy"} onClose={() => setLegalOpen(null)} />
      <TermsOfService open={legalOpen === "terms"} onClose={() => setLegalOpen(null)} />

      {!chatOpen && (
        <button onClick={() => setChatOpen(true)} className="chat-launcher" title="Open assistant">
          <Sparkles size={24} />
        </button>
      )}
      <Chat open={chatOpen} onClose={() => setChatOpen(false)} />
    </div>
  );
}
