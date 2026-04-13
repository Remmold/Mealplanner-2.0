import { useState } from "react";
import ProductList from "./components/ProductList";
import ProductDetail from "./components/ProductDetail";
import Categories from "./components/Categories";
import NutritionAggregator from "./components/NutritionAggregator";
import RecipeBuilder from "./components/RecipeBuilder";
import ShoppingList from "./components/ShoppingList";

type Tab = "recipe" | "shopping" | "products" | "categories" | "nutrition";

export default function App() {
  const [tab, setTab] = useState<Tab>("recipe");
  const [selectedCode, setSelectedCode] = useState<string | null>(null);

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", maxWidth: 960, margin: "0 auto", padding: 16 }}>
      <h1>Mealplanner API Tester</h1>
      <nav style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        {(["recipe", "shopping", "products", "categories", "nutrition"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => { setTab(t); setSelectedCode(null); }}
            style={{
              padding: "8px 16px",
              background: tab === t ? "#333" : "#eee",
              color: tab === t ? "#fff" : "#333",
              border: "none",
              borderRadius: 4,
              cursor: "pointer",
            }}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </nav>

      {tab === "recipe" && <RecipeBuilder />}
      {tab === "shopping" && <ShoppingList />}
      {tab === "products" && !selectedCode && (
        <ProductList onSelect={setSelectedCode} />
      )}
      {tab === "products" && selectedCode && (
        <ProductDetail code={selectedCode} onBack={() => setSelectedCode(null)} />
      )}
      {tab === "categories" && <Categories />}
      {tab === "nutrition" && <NutritionAggregator />}
    </div>
  );
}
