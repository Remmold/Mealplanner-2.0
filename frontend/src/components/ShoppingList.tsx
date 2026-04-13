import { useEffect, useState } from "react";
import {
  fetchRecipes,
  generateShoppingList,
  fetchStoreLayout,
  updateStoreLayout,
  type Recipe,
  type ShoppingList as ShoppingListType,
} from "../api";

interface Selection {
  recipe: Recipe;
  portions: number;
}

export default function ShoppingList() {
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [selections, setSelections] = useState<Record<string, Selection>>({});
  const [list, setList] = useState<ShoppingListType | null>(null);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const [layout, setLayout] = useState<string[]>([]);
  const [editLayout, setEditLayout] = useState(false);

  useEffect(() => {
    fetchRecipes().then(setRecipes).catch((e) => setError(String(e)));
    fetchStoreLayout().then(setLayout).catch(() => {});
  }, []);

  function toggleRecipe(recipe: Recipe) {
    setSelections((prev) => {
      const next = { ...prev };
      if (next[recipe.id]) {
        delete next[recipe.id];
      } else {
        next[recipe.id] = { recipe, portions: recipe.servings };
      }
      return next;
    });
  }

  function updatePortions(recipeId: string, portions: number) {
    setSelections((prev) => ({
      ...prev,
      [recipeId]: { ...prev[recipeId], portions: Math.max(1, portions) },
    }));
  }

  async function handleGenerate() {
    const picks = Object.values(selections);
    if (picks.length === 0) return;
    setLoading(true);
    setError("");
    setChecked(new Set());
    try {
      const result = await generateShoppingList(
        picks.map((s) => ({ recipe_id: s.recipe.id, portions: s.portions }))
      );
      setList(result);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  function toggleChecked(fdcId: number) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(fdcId)) next.delete(fdcId);
      else next.add(fdcId);
      return next;
    });
  }

  function moveCategory(idx: number, dir: -1 | 1) {
    const next = [...layout];
    const target = idx + dir;
    if (target < 0 || target >= next.length) return;
    [next[idx], next[target]] = [next[target], next[idx]];
    setLayout(next);
  }

  async function saveLayout() {
    try {
      const saved = await updateStoreLayout(layout);
      setLayout(saved);
      setEditLayout(false);
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <div>
      <h2>Shopping List</h2>

      {error && <p style={{ color: "red" }}>{error}</p>}

      {/* Recipe picker */}
      <div style={{ marginBottom: 16 }}>
        <h3 style={{ marginBottom: 8 }}>Pick recipes</h3>
        {recipes.length === 0 && <p style={{ color: "#999" }}>No recipes saved yet.</p>}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {recipes.map((r) => {
            const sel = selections[r.id];
            return (
              <div
                key={r.id}
                style={{
                  display: "flex", alignItems: "center", gap: 8,
                  padding: 8, background: sel ? "#eef6ff" : "#f9f9f9",
                  borderRadius: 4,
                }}
              >
                <input
                  type="checkbox"
                  checked={!!sel}
                  onChange={() => toggleRecipe(r)}
                />
                <span style={{ flex: 1, fontWeight: 500 }}>{r.name}</span>
                <span style={{ fontSize: 13, color: "#666" }}>
                  base: {r.servings} servings
                </span>
                {sel && (
                  <label style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 4 }}>
                    Portions:
                    <input
                      type="number"
                      min={1}
                      value={sel.portions}
                      onChange={(e) => updatePortions(r.id, Number(e.target.value) || 1)}
                      style={{ width: 60, padding: 3 }}
                    />
                  </label>
                )}
              </div>
            );
          })}
        </div>
        <button
          onClick={handleGenerate}
          disabled={loading || Object.keys(selections).length === 0}
          style={{
            marginTop: 12, padding: "8px 20px", fontWeight: 600,
            background: "#2563eb", color: "#fff", border: "none",
            borderRadius: 4, cursor: "pointer",
          }}
        >
          {loading ? "Generating..." : "Generate Shopping List"}
        </button>
      </div>

      {/* Store layout editor */}
      <div style={{ marginBottom: 16, padding: 12, background: "#f5f5f5", borderRadius: 6 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h4 style={{ margin: 0 }}>Store Layout (purchase order)</h4>
          <button onClick={() => setEditLayout(!editLayout)} style={{ padding: "3px 10px" }}>
            {editLayout ? "Close" : "Edit"}
          </button>
        </div>
        {editLayout && (
          <div style={{ marginTop: 8 }}>
            {layout.map((cat, i) => (
              <div key={cat} style={{ display: "flex", gap: 6, alignItems: "center", padding: 3 }}>
                <span style={{ width: 24, color: "#999", fontSize: 13 }}>{i + 1}.</span>
                <span style={{ flex: 1 }}>{cat}</span>
                <button onClick={() => moveCategory(i, -1)} disabled={i === 0} style={{ padding: "2px 8px" }}>↑</button>
                <button onClick={() => moveCategory(i, 1)} disabled={i === layout.length - 1} style={{ padding: "2px 8px" }}>↓</button>
              </div>
            ))}
            <button
              onClick={saveLayout}
              style={{
                marginTop: 8, padding: "6px 14px", background: "#16a34a",
                color: "#fff", border: "none", borderRadius: 4, cursor: "pointer",
              }}
            >
              Save layout
            </button>
          </div>
        )}
      </div>

      {/* Generated list */}
      {list && (
        <div>
          <h3>Shopping List</h3>
          {list.categories.length === 0 && (
            <p style={{ color: "#999" }}>No items.</p>
          )}
          {list.categories.map((cat) => (
            <div key={cat.category} style={{ marginBottom: 16 }}>
              <h4 style={{
                margin: "0 0 6px 0", padding: "4px 8px",
                background: "#333", color: "#fff", borderRadius: 4,
              }}>
                {cat.category}
              </h4>
              {cat.items.map((item) => (
                <label
                  key={item.fdc_id}
                  style={{
                    display: "flex", alignItems: "center", gap: 8,
                    padding: "4px 8px", borderBottom: "1px solid #f0f0f0",
                    textDecoration: checked.has(item.fdc_id) ? "line-through" : "none",
                    opacity: checked.has(item.fdc_id) ? 0.5 : 1,
                    cursor: "pointer",
                  }}
                >
                  <input
                    type="checkbox"
                    checked={checked.has(item.fdc_id)}
                    onChange={() => toggleChecked(item.fdc_id)}
                  />
                  <span style={{ flex: 1 }}>{item.name}</span>
                  <span style={{ fontWeight: 600 }}>
                    {item.display_quantity} {item.display_unit}
                  </span>
                  {item.display_unit !== "g" && (
                    <span style={{ fontSize: 12, color: "#999" }}>
                      ({Math.round(item.quantity_g)} g)
                    </span>
                  )}
                </label>
              ))}
            </div>
          ))}
          {list.missing_recipes.length > 0 && (
            <p style={{ color: "orange", fontSize: 13 }}>
              Some recipes not found: {list.missing_recipes.join(", ")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
