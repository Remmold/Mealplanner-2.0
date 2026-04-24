import { useEffect, useMemo, useState } from "react";
import {
  fetchShoppingTemplate,
  upsertShoppingTemplateItem,
  deleteShoppingTemplateItem,
  searchUsda,
  fetchIngredientUnits,
  type ShoppingTemplateItem,
  type UsdaSearchResult,
  type IngredientUnit,
} from "../api";

export default function ShoppingTemplate() {
  const [items, setItems] = useState<ShoppingTemplateItem[]>([]);
  const [units, setUnits] = useState<Record<number, IngredientUnit>>({});
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // Add-item picker state
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<UsdaSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [picked, setPicked] = useState<UsdaSearchResult | null>(null);
  const [qtyDisplay, setQtyDisplay] = useState<string>("1");
  const [note, setNote] = useState<string>("");

  // Inline edit state
  const [editingFdcId, setEditingFdcId] = useState<number | null>(null);
  const [editQty, setEditQty] = useState<string>("");
  const [editNote, setEditNote] = useState<string>("");

  useEffect(() => { void reload(); }, []);

  async function reload() {
    setLoading(true);
    try {
      const [list, u] = await Promise.all([fetchShoppingTemplate(), fetchIngredientUnits()]);
      setItems(list);
      setUnits(u);
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }

  async function runSearch() {
    if (query.trim().length < 2) return;
    setSearching(true);
    try { setResults(await searchUsda(query.trim(), 25)); }
    catch (e) { setError(String(e)); }
    finally { setSearching(false); }
  }

  function pickedUnit(): IngredientUnit | null {
    if (!picked) return null;
    return units[picked.fdc_id] ?? null;
  }

  function gramsFromDisplay(qty: number, unit: IngredientUnit | null): number {
    if (!unit) return qty;  // qty is already in grams
    return qty * unit.grams_per_unit;
  }

  async function handleAdd() {
    if (!picked) return;
    const qty = Number(qtyDisplay);
    if (!qty || qty <= 0) { setError("Enter a positive quantity"); return; }
    const grams = gramsFromDisplay(qty, pickedUnit());
    try {
      await upsertShoppingTemplateItem(picked.fdc_id, grams, note.trim() || null);
      setPicked(null);
      setQtyDisplay("1");
      setNote("");
      setQuery("");
      setResults([]);
      await reload();
    } catch (e) { setError(String(e)); }
  }

  function startEdit(item: ShoppingTemplateItem) {
    setEditingFdcId(item.fdc_id);
    setEditQty(String(item.display_quantity));
    setEditNote(item.note ?? "");
  }

  async function saveEdit(item: ShoppingTemplateItem) {
    const qty = Number(editQty);
    if (!qty || qty <= 0) { setError("Enter a positive quantity"); return; }
    const unit = units[item.fdc_id] ?? null;
    const grams = gramsFromDisplay(qty, unit);
    try {
      await upsertShoppingTemplateItem(item.fdc_id, grams, editNote.trim() || null);
      setEditingFdcId(null);
      await reload();
    } catch (e) { setError(String(e)); }
  }

  async function handleDelete(fdcId: number) {
    try {
      await deleteShoppingTemplateItem(fdcId);
      await reload();
    } catch (e) { setError(String(e)); }
  }

  const grouped = useMemo(() => {
    const map: Record<string, ShoppingTemplateItem[]> = {};
    for (const it of items) {
      (map[it.category] ||= []).push(it);
    }
    return map;
  }, [items]);

  const pickedUnitLabel = pickedUnit()?.display_unit ?? "g";
  const pickedGrams = picked
    ? gramsFromDisplay(Number(qtyDisplay) || 0, pickedUnit())
    : 0;

  return (
    <div className="col gap-4">
      <div className="card-warm">
        <p style={{ margin: 0 }}>
          Items here are <strong>always added</strong> to your weekly shopping list.
          Remove or adjust them per week on the list itself — those changes won't
          touch this template.
        </p>
      </div>

      {error && <div className="error">{error}</div>}

      {/* Add item */}
      <div className="card">
        <h3>Add baseline item</h3>
        <div className="row gap-2">
          <input
            className="input flex-1"
            placeholder="Search ingredient (e.g. milk, eggs)…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void runSearch(); }}
          />
          <button onClick={runSearch} disabled={searching || query.trim().length < 2} className="btn btn-primary btn-sm">
            {searching ? "Searching…" : "Search"}
          </button>
        </div>
        {results.length > 0 && !picked && (
          <div className="col-2 mt-3" style={{ maxHeight: 240, overflowY: "auto" }}>
            {results.map((r) => (
              <button
                key={r.fdc_id}
                onClick={() => setPicked(r)}
                className="row gap-2"
                style={{
                  padding: 8,
                  background: "var(--cream-2)",
                  borderRadius: "var(--r-sm)",
                  border: "1px solid var(--line)",
                  textAlign: "left",
                  cursor: "pointer",
                }}
              >
                <span className="flex-1">{r.name}</span>
                <span className="tiny muted">{r.mapped_category}</span>
              </button>
            ))}
          </div>
        )}
        {picked && (
          <div className="col-2 mt-3" style={{ padding: 12, background: "var(--sage-soft)", borderRadius: "var(--r-sm)" }}>
            <div className="row gap-2">
              <strong className="flex-1">{picked.name}</strong>
              <button onClick={() => setPicked(null)} className="btn btn-ghost btn-xs">Change</button>
            </div>
            <div className="row gap-2" style={{ alignItems: "flex-end" }}>
              <label className="field">
                <input
                  type="number"
                  min={0}
                  step={pickedUnit()?.round_step ?? 1}
                  className="input input-num"
                  value={qtyDisplay}
                  onChange={(e) => setQtyDisplay(e.target.value)}
                />
                <span className="tiny">{pickedUnitLabel}</span>
              </label>
              {pickedUnit() && (
                <span className="tiny muted" style={{ paddingBottom: 8 }}>
                  ≈ {Math.round(pickedGrams)} g
                </span>
              )}
              <input
                className="input flex-1"
                placeholder="Note (e.g. 'organic', optional)"
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
              <button onClick={handleAdd} className="btn btn-primary btn-sm">Add</button>
            </div>
          </div>
        )}
      </div>

      {/* Existing items */}
      <div className="card">
        <div className="row between mb-2">
          <h3 style={{ margin: 0 }}>Your baseline ({items.length})</h3>
          {loading && <span className="tiny muted">Loading…</span>}
        </div>
        {items.length === 0 && <div className="empty">No baseline items yet. Add what you always buy.</div>}
        {Object.entries(grouped).map(([category, rows]) => (
          <div key={category} className="mb-4">
            <div className="shop-cat-header">
              <span>{category}</span>
              <span className="shop-cat-count">{rows.length}</span>
            </div>
            {rows.map((item) => {
              const isEditing = editingFdcId === item.fdc_id;
              const unit = units[item.fdc_id] ?? null;
              return (
                <div key={item.fdc_id} className="shop-row" style={{ alignItems: "center" }}>
                  <span className="flex-1">
                    {item.name}
                    {item.note && !isEditing && (
                      <span className="tiny muted" style={{ marginLeft: 8 }}>— {item.note}</span>
                    )}
                  </span>
                  {isEditing ? (
                    <>
                      <label className="field">
                        <input
                          type="number"
                          min={0}
                          step={unit?.round_step ?? 1}
                          className="input input-num"
                          value={editQty}
                          onChange={(e) => setEditQty(e.target.value)}
                        />
                        <span className="tiny">{item.display_unit}</span>
                      </label>
                      <input
                        className="input"
                        style={{ width: 160 }}
                        placeholder="Note"
                        value={editNote}
                        onChange={(e) => setEditNote(e.target.value)}
                      />
                      <button onClick={() => saveEdit(item)} className="btn btn-primary btn-xs">Save</button>
                      <button onClick={() => setEditingFdcId(null)} className="btn btn-ghost btn-xs">Cancel</button>
                    </>
                  ) : (
                    <>
                      <span className="shop-qty">
                        {item.display_quantity} {item.display_unit}
                      </span>
                      <button onClick={() => startEdit(item)} className="btn btn-ghost btn-xs">Edit</button>
                      <button onClick={() => handleDelete(item.fdc_id)} className="btn btn-ghost btn-xs">✕</button>
                    </>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
