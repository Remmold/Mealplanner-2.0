import { useState } from "react";
import { aggregateNutrition, type AggregatedNutrition } from "../api";

interface Row { code: string; quantity_g: string; }

export default function NutritionAggregator() {
  const [rows, setRows] = useState<Row[]>([{ code: "", quantity_g: "100" }]);
  const [result, setResult] = useState<AggregatedNutrition | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function updateRow(i: number, field: keyof Row, value: string) {
    setRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, [field]: value } : r)));
  }
  function addRow() { setRows((prev) => [...prev, { code: "", quantity_g: "100" }]); }
  function removeRow(i: number) { setRows((prev) => prev.filter((_, idx) => idx !== i)); }

  async function submit() {
    setLoading(true); setError("");
    try {
      const items = rows
        .filter((r) => r.code.trim())
        .map((r) => ({ code: r.code.trim(), quantity_g: Number(r.quantity_g) || 100 }));
      if (items.length === 0) { setError("Add at least one product code"); return; }
      setResult(await aggregateNutrition(items));
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }

  return (
    <div className="col gap-5">
      <div className="hero">
        <h1>Nutrition aggregator</h1>
        <p>Add product barcodes and quantities to total their nutrition. Useful for analysing a packaged-product meal.</p>
      </div>

      <div className="row gap-5" style={{ alignItems: "flex-start", flexWrap: "wrap" }}>
        <div className="flex-1" style={{ minWidth: 320 }}>
          <div className="card">
            <h3>Items</h3>
            <div className="col-2">
              {rows.map((row, i) => (
                <div key={i} className="row gap-2">
                  <input
                    className="input flex-1"
                    placeholder="Product barcode"
                    value={row.code}
                    onChange={(e) => updateRow(i, "code", e.target.value)}
                  />
                  <input
                    className="input"
                    type="number"
                    placeholder="g"
                    value={row.quantity_g}
                    onChange={(e) => updateRow(i, "quantity_g", e.target.value)}
                    style={{ width: 80 }}
                  />
                  <span className="small muted">g</span>
                  <button onClick={() => removeRow(i)} disabled={rows.length <= 1} className="icon-btn">×</button>
                </div>
              ))}
            </div>
            <div className="row gap-2 mt-3">
              <button onClick={addRow} className="btn btn-sm">+ Add item</button>
              <button onClick={submit} disabled={loading} className="btn btn-primary">
                {loading ? "Loading..." : "Calculate"}
              </button>
            </div>
            {error && <div className="error mt-3">{error}</div>}
          </div>
        </div>

        <div className="flex-1" style={{ minWidth: 320 }}>
          {!result && <div className="card empty">No result yet — add items and calculate.</div>}
          {result && (
            <div className="card">
              <div className="row between mb-3">
                <h3 style={{ margin: 0 }}>Totals</h3>
                <span className="pill">{result.products_found} products</span>
              </div>
              <table className="table">
                <tbody>
                  {[
                    ["Weight", result.total_weight_g, "g"],
                    ["Energy", result.total_energy_kcal, "kcal"],
                    ["Protein", result.total_proteins_g, "g"],
                    ["Carbohydrates", result.total_carbohydrates_g, "g"],
                    ["Sugars", result.total_sugars_g, "g"],
                    ["Fat", result.total_fat_g, "g"],
                    ["Saturated Fat", result.total_saturated_fat_g, "g"],
                    ["Fiber", result.total_fiber_g, "g"],
                    ["Salt", result.total_salt_g, "g"],
                  ].map(([label, val, unit]) => (
                    <tr key={String(label)}>
                      <td>{label}</td>
                      <td className="right" style={{ fontWeight: 600 }}>{val} {unit}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {result.products_missing.length > 0 && (
                <p className="small mt-3" style={{ color: "var(--terracotta-dark)" }}>
                  Missing: {result.products_missing.join(", ")}
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
