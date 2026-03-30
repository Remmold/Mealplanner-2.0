import { useEffect, useState, useCallback } from "react";
import {
  fetchIngredientCategories,
  fetchIngredients,
  fetchRecipes,
  createRecipe,
  updateRecipe,
  deleteRecipe,
  aggregateRecipe,
  type Ingredient,
  type Recipe,
  type RecipeNutrition,
} from "../api";

interface RecipeItem {
  ingredient: Ingredient;
  quantity_g: number;
}

export default function RecipeBuilder() {
  // Saved recipes
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [activeRecipeId, setActiveRecipeId] = useState<string | null>(null);

  // Current recipe state
  const [recipeName, setRecipeName] = useState("Untitled Recipe");
  const [items, setItems] = useState<RecipeItem[]>([]);
  const [nutrition, setNutrition] = useState<RecipeNutrition | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  // Ingredient picker
  const [categories, setCategories] = useState<string[]>([]);
  const [allIngredients, setAllIngredients] = useState<Ingredient[]>([]);
  const [selectedCat, setSelectedCat] = useState("");
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    fetchIngredientCategories().then(setCategories).catch(() => {});
    fetchIngredients().then(setAllIngredients).catch((e) => setError(String(e)));
    loadRecipes();
  }, []);

  // Recalculate nutrition whenever items change
  useEffect(() => {
    if (items.length === 0) {
      setNutrition(null);
      return;
    }
    aggregateRecipe(items.map((i) => ({ fdc_id: i.ingredient.fdc_id, quantity_g: i.quantity_g })))
      .then(setNutrition)
      .catch(() => setNutrition(null));
  }, [items]);

  async function loadRecipes() {
    try {
      setRecipes(await fetchRecipes());
    } catch {}
  }

  const loadRecipeIntoEditor = useCallback(
    (recipe: Recipe) => {
      setActiveRecipeId(recipe.id);
      setRecipeName(recipe.name);
      // Map saved ingredients back to full Ingredient objects
      const loaded: RecipeItem[] = [];
      for (const ri of recipe.ingredients) {
        const ing = allIngredients.find((i) => i.fdc_id === ri.fdc_id);
        if (ing) {
          loaded.push({ ingredient: ing, quantity_g: ri.quantity_g });
        }
      }
      setItems(loaded);
      setDirty(false);
    },
    [allIngredients]
  );

  function newRecipe() {
    setActiveRecipeId(null);
    setRecipeName("Untitled Recipe");
    setItems([]);
    setDirty(false);
  }

  async function saveRecipe() {
    setSaving(true);
    try {
      const ingredients = items.map((i) => ({ fdc_id: i.ingredient.fdc_id, quantity_g: i.quantity_g }));
      if (activeRecipeId) {
        await updateRecipe(activeRecipeId, { name: recipeName, ingredients });
      } else {
        const created = await createRecipe(recipeName, ingredients);
        setActiveRecipeId(created.id);
      }
      setDirty(false);
      await loadRecipes();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteRecipe(id);
      if (activeRecipeId === id) newRecipe();
      await loadRecipes();
    } catch (e) {
      setError(String(e));
    }
  }

  function markDirty() { setDirty(true); }

  // Ingredient picker
  const filtered = allIngredients.filter((ing) => {
    if (selectedCat && ing.food_group !== selectedCat) return false;
    if (search && !ing.name.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  function addItem(ingredient: Ingredient) {
    if (items.some((i) => i.ingredient.fdc_id === ingredient.fdc_id)) return;
    setItems((prev) => [...prev, { ingredient, quantity_g: 100 }]);
    markDirty();
  }

  function updateQuantity(fdcId: number, qty: number) {
    setItems((prev) =>
      prev.map((i) => (i.ingredient.fdc_id === fdcId ? { ...i, quantity_g: qty } : i))
    );
    markDirty();
  }

  function removeItem(fdcId: number) {
    setItems((prev) => prev.filter((i) => i.ingredient.fdc_id !== fdcId));
    markDirty();
  }

  return (
    <div>
      <h2>Recipe Builder</h2>

      {/* Saved recipes bar */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        <button
          onClick={newRecipe}
          style={{ padding: "6px 14px", fontWeight: 600 }}
        >
          + New Recipe
        </button>
        {recipes.map((r) => (
          <div
            key={r.id}
            style={{
              display: "flex", alignItems: "center", gap: 4,
              padding: "4px 10px", borderRadius: 4,
              background: r.id === activeRecipeId ? "#333" : "#eee",
              color: r.id === activeRecipeId ? "#fff" : "#333",
              cursor: "pointer",
            }}
          >
            <span onClick={() => loadRecipeIntoEditor(r)}>{r.name}</span>
            <button
              onClick={(e) => { e.stopPropagation(); handleDelete(r.id); }}
              style={{
                background: "none", border: "none", cursor: "pointer",
                color: r.id === activeRecipeId ? "#ccc" : "#999",
                fontSize: 14, padding: "0 2px",
              }}
            >
              x
            </button>
          </div>
        ))}
      </div>

      {/* Recipe name + save */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 16 }}>
        <input
          value={recipeName}
          onChange={(e) => { setRecipeName(e.target.value); markDirty(); }}
          style={{
            fontSize: 18, fontWeight: "bold", border: "none",
            borderBottom: "2px solid #333", padding: 4, flex: 1,
          }}
        />
        <button
          onClick={saveRecipe}
          disabled={saving || (!dirty && activeRecipeId !== null)}
          style={{
            padding: "8px 20px", fontWeight: 600,
            background: dirty ? "#2563eb" : "#ccc",
            color: dirty ? "#fff" : "#666",
            border: "none", borderRadius: 4, cursor: dirty ? "pointer" : "default",
          }}
        >
          {saving ? "Saving..." : activeRecipeId ? "Save" : "Create"}
        </button>
      </div>

      {error && <p style={{ color: "red" }}>{error}</p>}

      <div style={{ display: "flex", gap: 16 }}>
        {/* Left: ingredient picker */}
        <div style={{ flex: 1 }}>
          <h3>Add Ingredients</h3>
          <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
            <select
              value={selectedCat}
              onChange={(e) => setSelectedCat(e.target.value)}
              style={{ padding: 6 }}
            >
              <option value="">All</option>
              {categories.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
            <input
              placeholder="Filter..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ padding: 6, flex: 1 }}
            />
          </div>

          <div style={{ maxHeight: 420, overflowY: "auto", border: "1px solid #ddd", borderRadius: 4 }}>
            {filtered.map((ing) => {
              const added = items.some((i) => i.ingredient.fdc_id === ing.fdc_id);
              return (
                <div
                  key={ing.fdc_id}
                  style={{
                    display: "flex", justifyContent: "space-between", alignItems: "center",
                    padding: "6px 10px", borderBottom: "1px solid #f0f0f0",
                    opacity: added ? 0.4 : 1,
                  }}
                >
                  <div>
                    <span style={{ fontWeight: 500 }}>{ing.name}</span>
                    <span style={{ fontSize: 12, color: "#888", marginLeft: 8 }}>
                      {ing.energy_kcal_100g} kcal/100g
                    </span>
                  </div>
                  <button
                    onClick={() => addItem(ing)}
                    disabled={added}
                    style={{ padding: "3px 10px", fontSize: 13 }}
                  >
                    {added ? "Added" : "+"}
                  </button>
                </div>
              );
            })}
            {filtered.length === 0 && (
              <p style={{ padding: 12, color: "#999" }}>No ingredients match.</p>
            )}
          </div>
        </div>

        {/* Right: recipe items + nutrition */}
        <div style={{ flex: 1 }}>
          <h3>Ingredients ({items.length})</h3>
          {items.length === 0 && (
            <p style={{ color: "#999" }}>Pick ingredients from the list.</p>
          )}

          {items.map((item) => (
            <div
              key={item.ingredient.fdc_id}
              style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: 8, marginBottom: 4, background: "#f9f9f9", borderRadius: 4,
              }}
            >
              <div style={{ flex: 1, fontWeight: 500, fontSize: 14 }}>
                {item.ingredient.name}
              </div>
              <input
                type="number"
                value={item.quantity_g}
                onChange={(e) => updateQuantity(item.ingredient.fdc_id, Number(e.target.value) || 0)}
                style={{ width: 70, padding: 4, textAlign: "right" }}
                min={0}
              />
              <span style={{ fontSize: 13 }}>g</span>
              <button onClick={() => removeItem(item.ingredient.fdc_id)} style={{ padding: "2px 8px" }}>
                X
              </button>
            </div>
          ))}

          {nutrition && (
            <div style={{ marginTop: 16, padding: 12, background: "#f0f7f0", borderRadius: 6 }}>
              <h4 style={{ margin: "0 0 8px 0" }}>Total Nutrition</h4>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
                <tbody>
                  {[
                    ["Weight", nutrition.total_weight_g, "g"],
                    ["Energy", nutrition.total_energy_kcal, "kcal"],
                    ["Protein", nutrition.total_proteins_g, "g"],
                    ["Carbs", nutrition.total_carbohydrates_g, "g"],
                    ["Sugars", nutrition.total_sugars_g, "g"],
                    ["Fat", nutrition.total_fat_g, "g"],
                    ["Saturated Fat", nutrition.total_saturated_fat_g, "g"],
                    ["Fiber", nutrition.total_fiber_g, "g"],
                    ["Salt", nutrition.total_salt_g, "g"],
                  ].map(([label, val, unit]) => (
                    <tr key={String(label)} style={{ borderBottom: "1px solid #ddd" }}>
                      <td style={{ padding: 3 }}>{label}</td>
                      <td style={{ padding: 3, textAlign: "right", fontWeight: 500 }}>
                        {val} {unit}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {nutrition.items_missing.length > 0 && (
                <p style={{ color: "orange", fontSize: 12, marginTop: 8 }}>
                  Missing data for some items.
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
