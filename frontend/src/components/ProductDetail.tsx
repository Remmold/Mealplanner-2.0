import { useEffect, useState } from "react";
import { fetchProduct, type Product } from "../api";

export default function ProductDetail({ code, onBack }: { code: string; onBack: () => void }) {
  const [product, setProduct] = useState<Product | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchProduct(code).then(setProduct).catch((e) => setError(String(e)));
  }, [code]);

  if (error) return <div><button onClick={onBack}>Back</button><p style={{ color: "red" }}>{error}</p></div>;
  if (!product) return <p>Loading...</p>;

  const flags = [
    ["High Protein", product.is_high_protein],
    ["Low Calorie", product.is_low_calorie],
    ["Gluten Free", product.is_gluten_free],
    ["Dairy Free", product.is_dairy_free],
    ["Nut Free", product.is_nut_free],
    ["Seafood Free", product.is_seafood_free],
  ] as const;

  return (
    <div>
      <button onClick={onBack} style={{ marginBottom: 12 }}>Back to list</button>
      <h2>GET /products/{code}</h2>
      <div style={{ display: "flex", gap: 16 }}>
        {product.image_url && (
          <img src={product.image_url} alt={product.product_name} style={{ maxWidth: 200, maxHeight: 200, objectFit: "contain" }} />
        )}
        <div>
          <h3>{product.product_name}</h3>
          <p><strong>Code:</strong> {product.code}</p>
          <p><strong>Brand:</strong> {product.brands ?? "-"}</p>
          <p><strong>Category:</strong> {product.category_label ?? "-"}</p>
          <p><strong>Nutriscore:</strong> {product.nutriscore_grade?.toUpperCase() ?? "-"}</p>
          <p><strong>NOVA Group:</strong> {product.nova_group ?? "-"}</p>
          <p><strong>Serving:</strong> {product.serving_size ?? "-"}</p>
        </div>
      </div>

      <h4 style={{ marginTop: 16 }}>Nutrition per 100g</h4>
      <table style={{ borderCollapse: "collapse" }}>
        <tbody>
          {[
            ["Energy", product.energy_kcal_100g, "kcal"],
            ["Protein", product.proteins_100g, "g"],
            ["Carbs", product.carbohydrates_100g, "g"],
            ["Sugars", product.sugars_100g, "g"],
            ["Fat", product.fat_100g, "g"],
            ["Saturated Fat", product.saturated_fat_100g, "g"],
            ["Fiber", product.fiber_100g, "g"],
            ["Salt", product.salt_100g, "g"],
          ].map(([label, val, unit]) => (
            <tr key={String(label)} style={{ borderBottom: "1px solid #eee" }}>
              <td style={{ padding: 4 }}>{label}</td>
              <td style={{ padding: 4, textAlign: "right" }}>{val != null ? `${val} ${unit}` : "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h4 style={{ marginTop: 16 }}>Flags</h4>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {flags.map(([label, val]) => (
          <span key={label} style={{
            padding: "4px 8px", borderRadius: 4, fontSize: 13,
            background: val ? "#d4edda" : "#f8f8f8", color: val ? "#155724" : "#888",
          }}>
            {label}: {val == null ? "?" : val ? "Yes" : "No"}
          </span>
        ))}
      </div>

      {product.allergens.length > 0 && (
        <>
          <h4 style={{ marginTop: 16 }}>Allergens</h4>
          <p>{product.allergens.join(", ")}</p>
        </>
      )}

      {product.ingredients_text && (
        <>
          <h4 style={{ marginTop: 16 }}>Ingredients</h4>
          <p style={{ fontSize: 13 }}>{product.ingredients_text}</p>
        </>
      )}
    </div>
  );
}
