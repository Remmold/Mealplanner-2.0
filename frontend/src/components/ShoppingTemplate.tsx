import { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";
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
import { Button, Card, Empty, ErrorBanner, Field, Input } from "./ui";

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
    <div className="col gap-3">
      <ErrorBanner>{error}</ErrorBanner>

      <div className="row gap-5 wrap items-start">
        {/* Left: add item */}
        <div className="flex-1 min-w-300 max-w-420">
          <Card>
            <h4 className="mb-2">Add item</h4>
            <div className="row gap-2">
              <Input
                className="flex-1"
                placeholder="Search (e.g. milk, eggs)…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") void runSearch(); }}
              />
              <Button onClick={runSearch} disabled={searching || query.trim().length < 2} variant="primary" size="sm">
                {searching ? "…" : "Search"}
              </Button>
            </div>
            {results.length > 0 && !picked && (
              <div className="col-2 mt-2 scroll-y maxh-200">
                {results.map((r) => (
                  <button key={r.fdc_id} onClick={() => setPicked(r)} className="option-row">
                    <span className="flex-1 small">{r.name}</span>
                    <span className="tiny muted">{r.mapped_category}</span>
                  </button>
                ))}
              </div>
            )}
            {picked && (
              <div className="col-2 mt-2 inset-accent">
                <div className="row gap-2">
                  <strong className="flex-1 small">{picked.name}</strong>
                  <Button onClick={() => setPicked(null)} variant="ghost" size="xs">Change</Button>
                </div>
                <div className="row gap-2">
                  <Field>
                    <Input
                      type="number"
                      min={0}
                      step={pickedUnit()?.round_step ?? 1}
                      numeric
                      value={qtyDisplay}
                      onChange={(e) => setQtyDisplay(e.target.value)}
                    />
                    <span className="tiny">{pickedUnitLabel}</span>
                  </Field>
                  {pickedUnit() && (
                    <span className="tiny muted">≈ {Math.round(pickedGrams)} g</span>
                  )}
                  <Button onClick={handleAdd} variant="primary" size="sm" className="ml-auto">Add</Button>
                </div>
                <Input
                  placeholder="Note (optional)"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                />
              </div>
            )}
          </Card>
        </div>

        {/* Right: existing items */}
        <div className="flex-1 min-w-320">
          <Card>
            <div className="row between mb-2">
              <h4 className="m-0">Your baseline ({items.length})</h4>
              {loading && <span className="tiny muted">Loading…</span>}
            </div>
            {items.length === 0 && <Empty>No baseline items yet. Add what you always buy.</Empty>}
            {Object.entries(grouped).map(([category, rows]) => (
              <div key={category} className="mb-4">
                <div className="shop-cat-header">
                  <span>{category}</span>
                  <span className="shop-cat-count">{rows.length}</span>
                </div>
                {rows.map((item) => {
                  const isEditing = editingFdcId === item.fdc_id;
                  const unit = units[item.fdc_id] ?? null;
                  if (isEditing) {
                    return (
                      <div key={item.fdc_id} className="edit-row">
                        <div className="row gap-2">
                          <strong className="flex-1 small">{item.name}</strong>
                          <Field>
                            <Input
                              type="number"
                              min={0}
                              step={unit?.round_step ?? 1}
                              autoFocus
                              numeric
                              value={editQty}
                              onChange={(e) => setEditQty(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") void saveEdit(item);
                                if (e.key === "Escape") setEditingFdcId(null);
                              }}
                            />
                            <span className="tiny">{item.display_unit}</span>
                          </Field>
                          <Button onClick={() => saveEdit(item)} variant="primary" size="sm">Save</Button>
                          <Button onClick={() => setEditingFdcId(null)} variant="ghost" size="sm">Cancel</Button>
                        </div>
                        <Input
                          placeholder="Note (optional)"
                          value={editNote}
                          onChange={(e) => setEditNote(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") void saveEdit(item);
                            if (e.key === "Escape") setEditingFdcId(null);
                          }}
                        />
                      </div>
                    );
                  }
                  return (
                    <div
                      key={item.fdc_id}
                      onClick={() => startEdit(item)}
                      className="shop-row"
                      title="Click to edit"
                    >
                      <span className="flex-1 small">
                        {item.name}
                        {item.note && (
                          <span className="tiny muted ml-2">— {item.note}</span>
                        )}
                      </span>
                      <span className="shop-qty">
                        {item.display_quantity} {item.display_unit}
                      </span>
                      <Button
                        onClick={(e) => { e.stopPropagation(); void handleDelete(item.fdc_id); }}
                        variant="ghost"
                        size="xs"
                        title="Remove from template"
                      >
                        <X size={14} />
                      </Button>
                    </div>
                  );
                })}
              </div>
            ))}
          </Card>
        </div>
      </div>
    </div>
  );
}
