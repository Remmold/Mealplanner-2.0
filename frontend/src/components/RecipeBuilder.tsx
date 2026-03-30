import { useEffect, useState } from "react";
import {
  fetchIngredientCategories,
  fetchIngredients,
  aggregateRecipe,
  type Ingredient,
  type RecipeNutrition,
} from "../api";

interface RecipeItem {
  ingredient: Ingredient;
  quantity_g: number;
}

export default function RecipeBuilder() {
  const [recipeName, setRecipeName] = useState("Untitled Recipe");
  const [items, setItems] = useState<RecipeItem[]>([]);
  const [nutrition, setNutrition] = useState<RecipeNutrition | null>(null);

  const [categories, setCategories] = useState<string[]>([]);
  const [allIngredients, setAllIngredients] = useState<Ingredient[]>([]);
  const [selectedCat, setSelectedCat] = useState("");
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    fetchIngredientCategories().then(setCategories).catch(() => {});
    fetchIngredients().then(setAllIngredients).catch((e) => setError(String(e)));
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

  // Client-side filtering (only 86 items, no need for server calls)
  const filtered = allIngredients.filter((ing) => {
    if (selectedCat && ing.food_group !== selectedCat) return false;
    if (search && !ing.name.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  function addItem(ingredient: Ingredient) {
    if (items.some((i) => i.ingredient.fdc_id === ingredient.fdc_id)) return;
    setItems((prev) => [...prev, { ingredient, quantity_g: 100 }]);
  }

  function updateQuantity(fdcId: number, qty: number) {
    setItems((prev) =>
      prev.map((i) => (i.ingredient.fdc_id === fdcId ? { ...i, quantity_g: qty } : i))
    );
  }

  function removeItem(fdcId: number) {
    setItems((prev) => prev.filter((i) => i.ingredient.fdc_id !== fdcId));
  }

  return (
    <div>
      <h2>Recipe Builder</h2>
      <input
        value={recipeName}
        onChange={(e) => setRecipeName(e.target.value)}
        style={{
          fontSize: 18, fontWeight: "bold", border: "none",
          borderBottom: "2px solid #333", padding: 4, marginBottom: 16, width: "100%",
        }}
      />

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

          {error && <p style={{ color: "red" }}>{error}</p>}

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
          <h3>Recipe ({items.length} ingredients)</h3>
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
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 500, fontSize: 14 }}>{item.ingredient.name}</div>
                {item.ingredient.subcategory && (
                  <div style={{ fontSize: 11, color: "#888" }}>
                    Linked to "{item.ingredient.subcategory}" branded products
                  </div>
                )}
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
