import { useEffect, useState } from "react";
import {
  fetchRecipes,
  generateShoppingList,
  fetchStoreLayout,
  updateStoreLayout,
  type Recipe,
  type ShoppingList as ShoppingListType,
} from "../api";

interface Selection { recipe: Recipe; portions: number; }

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
      if (next[recipe.id]) delete next[recipe.id];
      else next[recipe.id] = { recipe, portions: recipe.servings };
      return next;
    });
  }

  function updatePortions(recipeId: string, portions: number) {
    setSelections((prev) => ({
      ...prev, [recipeId]: { ...prev[recipeId], portions: Math.max(1, portions) },
    }));
  }

  async function handleGenerate() {
    const picks = Object.values(selections);
    if (picks.length === 0) return;
    setLoading(true); setError(""); setChecked(new Set());
    try {
      const result = await generateShoppingList(
        picks.map((s) => ({ recipe_id: s.recipe.id, portions: s.portions }))
      );
      setList(result);
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
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
      setLayout(saved); setEditLayout(false);
    } catch (e) { setError(String(e)); }
  }

  const totalItems = list?.categories.reduce((sum, c) => sum + c.items.length, 0) ?? 0;
  const checkedCount = checked.size;

  return (
    <div className="col gap-5">
      <div className="hero">
        <h1>Shopping list</h1>
        <p>Pick recipes and portions. We'll consolidate ingredients, convert to friendly units, and order everything in your store's aisle layout.</p>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="row gap-5" style={{ alignItems: "flex-start", flexWrap: "wrap" }}>
        {/* Left: pick recipes */}
        <div className="flex-1" style={{ minWidth: 320 }}>
          <div className="card">
            <h3>Pick recipes</h3>
            {recipes.length === 0 && <div className="empty">No recipes saved yet.</div>}
            <div className="col-2">
              {recipes.map((r) => {
                const sel = selections[r.id];
                return (
                  <div key={r.id} className="row gap-3" style={{
                    padding: 10,
                    background: sel ? "var(--sage-soft)" : "var(--cream-2)",
                    borderRadius: "var(--r-sm)",
                    border: sel ? "1px solid #cddec6" : "1px solid var(--line)",
                  }}>
                    <input
                      type="checkbox"
                      checked={!!sel}
                      onChange={() => toggleRecipe(r)}
                    />
                    <div className="flex-1">
                      <div style={{ fontWeight: 500 }}>{r.name}</div>
                      <div className="tiny muted">base: {r.servings} servings</div>
                    </div>
                    {sel && (
                      <label className="field">
                        <input
                          type="number"
                          min={1}
                          className="input input-num"
                          value={sel.portions}
                          onChange={(e) => updatePortions(r.id, Number(e.target.value) || 1)}
                        />
                        <span className="tiny">portions</span>
                      </label>
                    )}
                  </div>
                );
              })}
            </div>
            <button
              onClick={handleGenerate}
              disabled={loading || Object.keys(selections).length === 0}
              className="btn btn-primary btn-block mt-4"
            >
              {loading ? "Generating..." : "Generate shopping list"}
            </button>
          </div>

          <div className="card-soft mt-4">
            <div className="row between mb-2">
              <h4 style={{ margin: 0 }}>Store layout</h4>
              <button onClick={() => setEditLayout(!editLayout)} className="btn btn-ghost btn-sm">
                {editLayout ? "Close" : "Edit"}
              </button>
            </div>
            {!editLayout && (
              <p className="small muted" style={{ margin: 0 }}>
                Items appear in this order on your list. Edit to match your store's aisle flow.
              </p>
            )}
            {editLayout && (
              <div className="col-2">
                {layout.map((cat, i) => (
                  <div key={cat} className="row gap-2" style={{ padding: 4 }}>
                    <span className="muted small" style={{ width: 24 }}>{i + 1}.</span>
                    <span className="flex-1">{cat}</span>
                    <button onClick={() => moveCategory(i, -1)} disabled={i === 0} className="btn btn-xs">↑</button>
                    <button onClick={() => moveCategory(i, 1)} disabled={i === layout.length - 1} className="btn btn-xs">↓</button>
                  </div>
                ))}
                <button onClick={saveLayout} className="btn btn-primary btn-sm mt-2">Save layout</button>
              </div>
            )}
          </div>
        </div>

        {/* Right: generated list */}
        <div className="flex-1" style={{ minWidth: 320 }}>
          {!list && <div className="card empty">No list yet — pick some recipes.</div>}
          {list && (
            <div className="card">
              <div className="row between mb-3">
                <h3 style={{ margin: 0 }}>Your list</h3>
                <span className="pill">{checkedCount} / {totalItems} done</span>
              </div>
              {list.categories.length === 0 && <div className="empty">No items.</div>}
              {list.categories.map((cat) => (
                <div key={cat.category} className="mb-4">
                  <div className="shop-cat-header">
                    <span>{cat.category}</span>
                    <span className="shop-cat-count">{cat.items.length}</span>
                  </div>
                  {cat.items.map((item) => {
                    const isChecked = checked.has(item.fdc_id);
                    return (
                      <label key={item.fdc_id} className={`shop-row ${isChecked ? "checked" : ""}`}>
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={() => toggleChecked(item.fdc_id)}
                        />
                        <span className="flex-1">{item.name}</span>
                        <span className={`shop-qty ${isChecked ? "checked" : ""}`}>
                          {item.display_quantity} {item.display_unit}
                        </span>
                        {item.display_unit !== "g" && (
                          <span className="tiny muted">({Math.round(item.quantity_g)} g)</span>
                        )}
                      </label>
                    );
                  })}
                </div>
              ))}
              {list.missing_recipes.length > 0 && (
                <p className="small" style={{ color: "var(--terracotta-dark)" }}>
                  Some recipes not found: {list.missing_recipes.join(", ")}
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
