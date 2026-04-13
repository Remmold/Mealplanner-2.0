import { useEffect, useState } from "react";
import { onNavigate } from "./api";
import ProductList from "./components/ProductList";
import ProductDetail from "./components/ProductDetail";
import Categories from "./components/Categories";
import NutritionAggregator from "./components/NutritionAggregator";
import RecipeBuilder from "./components/RecipeBuilder";
import ShoppingList from "./components/ShoppingList";
import MealPlan from "./components/MealPlan";
import Chat from "./components/Chat";
import Profile from "./components/Profile";

type Tab = "recipe" | "plan" | "shopping" | "profile" | "products" | "categories" | "nutrition";

const TABS: { id: Tab; label: string }[] = [
  { id: "recipe",     label: "Recipes" },
  { id: "plan",       label: "Meal Plan" },
  { id: "shopping",   label: "Shopping" },
  { id: "profile",    label: "Household" },
  { id: "products",   label: "Products" },
  { id: "categories", label: "Categories" },
  { id: "nutrition",  label: "Nutrition" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("recipe");
  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [initialRecipeId, setInitialRecipeId] = useState<string | null>(null);

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
                onClick={() => { setTab(t.id); setSelectedCode(null); }}
                className={`nav-btn ${tab === t.id ? "active" : ""}`}
              >
                {t.label}
              </button>
            ))}
          </nav>
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
        {tab === "products" && !selectedCode && (
          <ProductList onSelect={setSelectedCode} />
        )}
        {tab === "products" && selectedCode && (
          <ProductDetail code={selectedCode} onBack={() => setSelectedCode(null)} />
        )}
        {tab === "categories" && <Categories />}
        {tab === "nutrition" && <NutritionAggregator />}
      </main>

      <footer className="app-footer">
        Hearth · Mealplanner 2.0
      </footer>

      {!chatOpen && (
        <button onClick={() => setChatOpen(true)} className="chat-launcher" title="Open assistant">
          ✦
        </button>
      )}
      <Chat open={chatOpen} onClose={() => setChatOpen(false)} />
    </div>
  );
}
