import { useEffect, useState } from "react";
import {
  fetchSubcategories,
  fetchProducts,
  aggregateNutrition,
  type ProductSummary,
  type AggregatedNutrition,
} from "../api";

interface RecipeItem {
  product: ProductSummary;
  quantity_g: number;
}

export default function RecipeBuilder() {
  const [recipeName, setRecipeName] = useState("Untitled Recipe");
  const [items, setItems] = useState<RecipeItem[]>([]);
  const [nutrition, setNutrition] = useState<AggregatedNutrition | null>(null);

  // Product picker state
  const [subcategories, setSubcategories] = useState<string[]>([]);
  const [selectedSub, setSelectedSub] = useState("");
  const [search, setSearch] = useState("");
  const [results, setResults] = useState<ProductSummary[]>([]);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchSubcategories().then(setSubcategories).catch(() => {});
  }, []);

  // Recalculate nutrition whenever items change
  useEffect(() => {
    if (items.length === 0) {
      setNutrition(null);
      return;
    }
    aggregateNutrition(items.map((i) => ({ code: i.product.code, quantity_g: i.quantity_g })))
      .then(setNutrition)
      .catch(() => setNutrition(null));
  }, [items]);

  async function searchProducts() {
    if (!selectedSub && !search) return;
    setSearching(true);
    setError("");
    try {
      const params: Record<string, string> = { page_size: "20", sort_by: "data_completeness", sort_order: "desc" };
      if (selectedSub) params.subcategory = selectedSub;
      if (search) params.search = search;
      const data = await fetchProducts(params);
      setResults(data.items);
    } catch (e) {
      setError(String(e));
    } finally {
      setSearching(false);
    }
  }

  function addItem(product: ProductSummary) {
    if (items.some((i) => i.product.code === product.code)) return;
    setItems((prev) => [...prev, { product, quantity_g: 100 }]);
  }

  function updateQuantity(code: string, qty: number) {
    setItems((prev) => prev.map((i) => (i.product.code === code ? { ...i, quantity_g: qty } : i)));
  }

  function removeItem(code: string) {
    setItems((prev) => prev.filter((i) => i.product.code !== code));
  }

  return (
    <div>
      <h2>Recipe Builder</h2>
      <input
        value={recipeName}
        onChange={(e) => setRecipeName(e.target.value)}
        style={{ fontSize: 18, fontWeight: "bold", border: "none", borderBottom: "2px solid #333", padding: 4, marginBottom: 16, width: "100%" }}
      />

      <div style={{ display: "flex", gap: 16 }}>
        {/* Left: product picker */}
        <div style={{ flex: 1 }}>
          <h3>Find Ingredients</h3>
          <div style={{ display: "flex", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
            <select
              value={selectedSub}
              onChange={(e) => setSelectedSub(e.target.value)}
              style={{ padding: 6 }}
            >
              <option value="">All subcategories</option>
              {subcategories.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <input
              placeholder="Search name/brand..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && searchProducts()}
              style={{ padding: 6, flex: 1, minWidth: 150 }}
            />
            <button onClick={searchProducts} style={{ padding: "6px 12px" }}>Search</button>
          </div>

          {searching && <p>Searching...</p>}
          {error && <p style={{ color: "red" }}>{error}</p>}

          {results.length > 0 && (
            <div style={{ maxHeight: 350, overflowY: "auto", border: "1px solid #ddd", borderRadius: 4 }}>
              {results.map((p) => {
                const alreadyAdded = items.some((i) => i.product.code === p.code);
                return (
                  <div
                    key={p.code}
                    style={{
                      display: "flex", justifyContent: "space-between", alignItems: "center",
                      padding: 8, borderBottom: "1px solid #eee",
                      opacity: alreadyAdded ? 0.5 : 1,
                    }}
                  >
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 500 }}>{p.product_name}</div>
                      <div style={{ fontSize: 12, color: "#666" }}>
                        {p.brands ?? ""} {p.subcategory ? `| ${p.subcategory}` : ""}
                        {p.energy_kcal_100g != null ? ` | ${p.energy_kcal_100g} kcal/100g` : ""}
                      </div>
                    </div>
                    <button
                      onClick={() => addItem(p)}
                      disabled={alreadyAdded}
                      style={{ padding: "4px 10px", marginLeft: 8 }}
                    >
                      {alreadyAdded ? "Added" : "+ Add"}
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Right: recipe items + nutrition */}
        <div style={{ flex: 1 }}>
          <h3>Ingredients ({items.length})</h3>
          {items.length === 0 && (
            <p style={{ color: "#999" }}>Search for products and add them to your recipe.</p>
          )}

          {items.map((item) => (
            <div
              key={item.product.code}
              style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: 8, marginBottom: 4, background: "#f9f9f9", borderRadius: 4,
              }}
            >
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 500, fontSize: 14 }}>{item.product.product_name}</div>
                <div style={{ fontSize: 12, color: "#666" }}>{item.product.brands ?? ""}</div>
              </div>
              <input
                type="number"
                value={item.quantity_g}
                onChange={(e) => updateQuantity(item.product.code, Number(e.target.value) || 0)}
                style={{ width: 70, padding: 4, textAlign: "right" }}
                min={0}
              />
              <span style={{ fontSize: 13 }}>g</span>
              <button onClick={() => removeItem(item.product.code)} style={{ padding: "2px 8px" }}>X</button>
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
              {nutrition.products_missing.length > 0 && (
                <p style={{ color: "orange", fontSize: 12, marginTop: 8 }}>
                  Missing nutrition data for: {nutrition.products_missing.join(", ")}
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
