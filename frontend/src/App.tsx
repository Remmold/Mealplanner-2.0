import { useEffect, useMemo, useState } from "react";
import { LogOut, Sparkles } from "lucide-react";
import { onNavigate } from "./api";
import { useAuth } from "./auth/AuthProvider";
import SignIn from "./auth/SignIn";
import CreateOrJoinHousehold from "./auth/CreateOrJoinHousehold";
import ProfileWizard, { wizardWasDismissed } from "./auth/ProfileWizard";
import PrivacyPolicy from "./legal/PrivacyPolicy";
import TermsOfService from "./legal/TermsOfService";
import { Button } from "./components/ui";
import RecipeBuilder from "./components/RecipeBuilder";
import ShoppingList from "./components/ShoppingList";
import MealPlan from "./components/MealPlan";
import Chat from "./components/Chat";
import Profile from "./components/Profile";

type Tab = "recipe" | "plan" | "shopping" | "profile";

const TABS: { id: Tab; label: string }[] = [
  { id: "recipe",     label: "Recipes" },
  { id: "plan",       label: "Meal Plan" },
  { id: "shopping",   label: "Shopping" },
  { id: "profile",    label: "Household" },
];

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

  const [tab, setTab] = useState<Tab>("recipe");
  const [chatOpen, setChatOpen] = useState(false);
  const [initialRecipeId, setInitialRecipeId] = useState<string | null>(null);
  const [showWizardDismissed, setShowWizardDismissed] = useState(wizardWasDismissed);
  const [legalOpen, setLegalOpen] = useState<"privacy" | "terms" | null>(null);

  useEffect(() => {
    return onNavigate((intent) => {
      if (intent.tab === "recipe") {
        setTab("recipe");
        if (intent.recipe_id) setInitialRecipeId(intent.recipe_id);
        setChatOpen(false);
      } else if (intent.tab === "plan") {
        setTab("plan");
        setChatOpen(false);
      }
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

  if (!showWizardDismissed) {
    return <ProfileWizard onComplete={() => setShowWizardDismissed(true)} />;
  }

  return (
    <div className="app-shell">
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
