import { useState } from "react";
import ProductList from "./components/ProductList";
import ProductDetail from "./components/ProductDetail";
import Categories from "./components/Categories";
import NutritionAggregator from "./components/NutritionAggregator";
import RecipeBuilder from "./components/RecipeBuilder";
import ShoppingList from "./components/ShoppingList";
import MealPlan from "./components/MealPlan";
import Chat from "./components/Chat";

type Tab = "recipe" | "plan" | "shopping" | "products" | "categories" | "nutrition";

const TABS: { id: Tab; label: string }[] = [
  { id: "recipe",     label: "Recipes" },
  { id: "plan",       label: "Meal Plan" },
  { id: "shopping",   label: "Shopping" },
  { id: "products",   label: "Products" },
  { id: "categories", label: "Categories" },
  { id: "nutrition",  label: "Nutrition" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("recipe");
  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(false);

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
        {tab === "recipe" && <RecipeBuilder />}
        {tab === "plan" && <MealPlan />}
        {tab === "shopping" && <ShoppingList />}
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
