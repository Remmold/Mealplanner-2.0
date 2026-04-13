import { useEffect, useState } from "react";
import { fetchProduct, type Product } from "../api";

export default function ProductDetail({ code, onBack }: { code: string; onBack: () => void }) {
  const [product, setProduct] = useState<Product | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchProduct(code).then(setProduct).catch((e) => setError(String(e)));
  }, [code]);

  if (error) return (
    <div className="col gap-3">
      <button onClick={onBack} className="btn btn-ghost btn-sm">← Back</button>
      <div className="error">{error}</div>
    </div>
  );
  if (!product) return <p className="muted">Loading...</p>;

  const flags = [
    ["High Protein", product.is_high_protein],
    ["Low Calorie", product.is_low_calorie],
    ["Gluten Free", product.is_gluten_free],
    ["Dairy Free", product.is_dairy_free],
    ["Nut Free", product.is_nut_free],
    ["Seafood Free", product.is_seafood_free],
  ] as const;

  return (
    <div className="col gap-4">
      <button onClick={onBack} className="btn btn-ghost btn-sm" style={{ alignSelf: "flex-start" }}>← Back</button>

      <div className="card">
        <div className="row gap-5" style={{ alignItems: "flex-start", flexWrap: "wrap" }}>
          {product.image_url && (
            <img
              src={product.image_url}
              alt={product.product_name}
              style={{ maxWidth: 200, maxHeight: 200, objectFit: "contain", borderRadius: "var(--r-md)", background: "var(--cream-2)" }}
            />
          )}
          <div className="flex-1" style={{ minWidth: 240 }}>
            <h2>{product.product_name}</h2>
            <div className="row wrap gap-2 mb-3">
              {product.brands && <span className="pill">{product.brands}</span>}
              {product.category_label && <span className="pill">{product.category_label}</span>}
              {product.nutriscore_grade && (
                <span className="pill pill-warm">Nutri-Score {product.nutriscore_grade.toUpperCase()}</span>
              )}
              {product.nova_group && <span className="pill">NOVA {product.nova_group}</span>}
            </div>
            <p className="small muted">Code {product.code}{product.serving_size ? ` · serving ${product.serving_size}` : ""}</p>
          </div>
        </div>
      </div>

      <div className="row gap-4" style={{ alignItems: "flex-start", flexWrap: "wrap" }}>
        <div className="flex-1" style={{ minWidth: 320 }}>
          <div className="card">
            <h3>Nutrition · per 100g</h3>
            <table className="table">
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
                  <tr key={String(label)}>
                    <td>{label}</td>
                    <td className="right" style={{ fontWeight: 600 }}>{val != null ? `${val} ${unit}` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="flex-1" style={{ minWidth: 320 }}>
          <div className="card">
            <h3>Dietary flags</h3>
            <div className="row wrap gap-2">
              {flags.map(([label, val]) => (
                <span key={label} className="pill" style={
                  val ? { background: "var(--sage-soft)", color: "var(--sage-dark)", borderColor: "#cddec6" }
                  : val === false ? { background: "var(--cream-2)", color: "var(--taupe-2)" }
                  : { background: "var(--cream-2)", color: "var(--taupe-3)" }
                }>
                  {label}: {val == null ? "?" : val ? "Yes" : "No"}
                </span>
              ))}
            </div>

            {product.allergens.length > 0 && (
              <>
                <h4 className="mt-4">Allergens</h4>
                <p className="small">{product.allergens.join(", ")}</p>
              </>
            )}

            {product.ingredients_text && (
              <>
                <h4 className="mt-4">Ingredients</h4>
                <p className="small muted">{product.ingredients_text}</p>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
