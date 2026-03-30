import { useState } from "react";
import { aggregateNutrition, type AggregatedNutrition } from "../api";

interface Row {
  code: string;
  quantity_g: string;
}

export default function NutritionAggregator() {
  const [rows, setRows] = useState<Row[]>([{ code: "", quantity_g: "100" }]);
  const [result, setResult] = useState<AggregatedNutrition | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function updateRow(i: number, field: keyof Row, value: string) {
    setRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, [field]: value } : r)));
  }

  function addRow() {
    setRows((prev) => [...prev, { code: "", quantity_g: "100" }]);
  }

  function removeRow(i: number) {
    setRows((prev) => prev.filter((_, idx) => idx !== i));
  }

  async function submit() {
    setLoading(true);
    setError("");
    try {
      const items = rows
        .filter((r) => r.code.trim())
        .map((r) => ({ code: r.code.trim(), quantity_g: Number(r.quantity_g) || 100 }));
      if (items.length === 0) {
        setError("Add at least one product code");
        return;
      }
      setResult(await aggregateNutrition(items));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <h2>POST /nutrition/aggregate</h2>
      <p style={{ fontSize: 13, color: "#666" }}>
        Enter product barcodes and quantities (grams) to calculate total nutrition.
      </p>

      {rows.map((row, i) => (
        <div key={i} style={{ display: "flex", gap: 8, marginBottom: 6 }}>
          <input
            placeholder="Product code (barcode)"
            value={row.code}
            onChange={(e) => updateRow(i, "code", e.target.value)}
            style={{ flex: 1, padding: 6 }}
          />
          <input
            type="number"
            placeholder="Grams"
            value={row.quantity_g}
            onChange={(e) => updateRow(i, "quantity_g", e.target.value)}
            style={{ width: 80, padding: 6 }}
          />
          <button onClick={() => removeRow(i)} disabled={rows.length <= 1}>X</button>
        </div>
      ))}

      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        <button onClick={addRow}>+ Add item</button>
        <button onClick={submit} disabled={loading} style={{ padding: "6px 16px" }}>
          {loading ? "Loading..." : "Calculate"}
        </button>
      </div>

      {error && <p style={{ color: "red" }}>{error}</p>}

      {result && (
        <table style={{ marginTop: 16, borderCollapse: "collapse" }}>
          <tbody>
            {[
              ["Total Weight", result.total_weight_g, "g"],
              ["Energy", result.total_energy_kcal, "kcal"],
              ["Protein", result.total_proteins_g, "g"],
              ["Carbohydrates", result.total_carbohydrates_g, "g"],
              ["Sugars", result.total_sugars_g, "g"],
              ["Fat", result.total_fat_g, "g"],
              ["Saturated Fat", result.total_saturated_fat_g, "g"],
              ["Fiber", result.total_fiber_g, "g"],
              ["Salt", result.total_salt_g, "g"],
            ].map(([label, val, unit]) => (
              <tr key={String(label)} style={{ borderBottom: "1px solid #eee" }}>
                <td style={{ padding: 4 }}>{label}</td>
                <td style={{ padding: 4, textAlign: "right" }}>{val} {unit}</td>
              </tr>
            ))}
            <tr style={{ borderBottom: "1px solid #eee" }}>
              <td style={{ padding: 4 }}>Products found</td>
              <td style={{ padding: 4, textAlign: "right" }}>{result.products_found}</td>
            </tr>
          </tbody>
          {result.products_missing.length > 0 && (
            <tfoot>
              <tr>
                <td colSpan={2} style={{ padding: 4, color: "orange" }}>
                  Missing: {result.products_missing.join(", ")}
                </td>
              </tr>
            </tfoot>
          )}
        </table>
      )}
    </div>
  );
}
