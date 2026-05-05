import { useEffect, useState } from "react";
import {
  fetchRecipes,
  generateShoppingList,
  fetchStoreLayout,
  updateStoreLayout,
  type Recipe,
  type ShoppingList as ShoppingListType,
} from "../api";
import ShoppingTemplate from "./ShoppingTemplate";

interface Selection { recipe: Recipe; portions: number; }

type View = "list" | "template";

export default function ShoppingList() {
  const [view, setView] = useState<View>("list");

  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [selections, setSelections] = useState<Record<string, Selection>>({});
  const [list, setList] = useState<ShoppingListType | null>(null);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  // Items the user has removed *just for this week* (ephemeral — not saved).
  const [hidden, setHidden] = useState<Set<number>>(new Set());
  // Ephemeral per-week display-quantity overrides. Keyed on fdc_id, value is the
  // user-edited display_quantity (unit stays the same). Cleared on regenerate.
  const [qtyOverride, setQtyOverride] = useState<Record<number, number>>({});
  const [editingQty, setEditingQty] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<string>("");
  const [includeTemplate, setIncludeTemplate] = useState(true);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const [layout, setLayout] = useState<string[]>([]);
  const [editLayout, setEditLayout] = useState(false);
  const [recipeFilter, setRecipeFilter] = useState("");

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
    if (picks.length === 0 && !includeTemplate) return;
    setLoading(true); setError(""); setChecked(new Set()); setHidden(new Set()); setQtyOverride({}); setEditingQty(null);
    try {
      const result = await generateShoppingList(
        picks.map((s) => ({ recipe_id: s.recipe.id, portions: s.portions })),
        includeTemplate,
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

  function hideForWeek(fdcId: number) {
    setHidden((prev) => {
      const next = new Set(prev);
      next.add(fdcId);
      return next;
    });
  }

  function restoreItem(fdcId: number) {
    setHidden((prev) => {
      const next = new Set(prev);
      next.delete(fdcId);
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

  const visibleCategories = list?.categories
    .map((c) => ({ ...c, items: c.items.filter((it) => !hidden.has(it.fdc_id)) }))
    .filter((c) => c.items.length > 0) ?? [];
  const totalItems = visibleCategories.reduce((sum, c) => sum + c.items.length, 0);
  const checkedCount = checked.size;
  const hiddenItems = list
    ? list.categories.flatMap((c) => c.items).filter((it) => hidden.has(it.fdc_id))
    : [];

  if (view === "template") {
    return (
      <div className="col gap-3">
        <div className="row between" style={{ alignItems: "baseline" }}>
          <div>
            <h2 style={{ margin: 0 }}>Shopping template</h2>
            <span className="small muted">
              Baseline items — preprinted into every weekly list. Edits here are permanent.
            </span>
          </div>
          <button onClick={() => setView("list")} className="btn btn-ghost btn-sm">← Back to list</button>
        </div>
        <ShoppingTemplate />
      </div>
    );
  }

  return (
    <div className="col gap-5">
      <div className="hero">
        <h1>Shopping list</h1>
        <p>Pick recipes and portions. We'll consolidate ingredients, convert to friendly units, and order everything in your store's aisle layout.</p>
      </div>

      <div className="row gap-2">
        <button onClick={() => setView("template")} className="btn btn-ghost btn-sm">
          Manage shopping template →
        </button>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="row gap-5" style={{ alignItems: "flex-start", flexWrap: "wrap" }}>
        {/* Left: pick recipes */}
        <div className="flex-1" style={{ minWidth: 320 }}>
          <div className="card">
            <div className="row between mb-2" style={{ alignItems: "baseline" }}>
              <h4 style={{ margin: 0 }}>Pick recipes</h4>
              <span className="tiny muted">
                {Object.keys(selections).length} selected · {recipes.length} total
              </span>
            </div>
            {recipes.length === 0 ? (
              <div className="empty">No recipes saved yet.</div>
            ) : (
              <>
                <input
                  className="input mb-2"
                  placeholder="Filter recipes…"
                  value={recipeFilter}
                  onChange={(e) => setRecipeFilter(e.target.value)}
                />
                <div
                  style={{
                    maxHeight: 340,
                    overflowY: "auto",
                    border: "1px solid var(--line)",
                    borderRadius: "var(--r-sm)",
                    padding: 4,
                  }}
                >
                  {recipes
                    .filter((r) => r.name.toLowerCase().includes(recipeFilter.toLowerCase()))
                    .map((r) => {
                      const sel = selections[r.id];
                      return (
                        <div
                          key={r.id}
                          onClick={() => toggleRecipe(r)}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 8,
                            padding: "4px 8px",
                            background: sel ? "var(--sage-soft)" : "transparent",
                            borderRadius: "var(--r-sm)",
                            cursor: "pointer",
                          }}
                        >
                          <input
                            type="checkbox"
                            checked={!!sel}
                            onChange={() => toggleRecipe(r)}
                            onClick={(e) => e.stopPropagation()}
                          />
                          <span className="flex-1 small" style={{ fontWeight: sel ? 500 : 400 }}>
                            {r.name}
                          </span>
                          {sel ? (
                            <label className="field" onClick={(e) => e.stopPropagation()}>
                              <input
                                type="number"
                                min={1}
                                className="input input-num"
                                style={{ width: 52 }}
                                value={sel.portions}
                                onChange={(e) => updatePortions(r.id, Number(e.target.value) || 1)}
                              />
                              <span className="tiny">pt</span>
                            </label>
                          ) : (
                            <span className="tiny muted">{r.servings}s</span>
                          )}
                        </div>
                      );
                    })}
                </div>
              </>
            )}
            <label className="row gap-2 mt-2" style={{ alignItems: "center" }}>
              <input
                type="checkbox"
                checked={includeTemplate}
                onChange={(e) => setIncludeTemplate(e.target.checked)}
              />
              <span className="small">Include household template (baseline items)</span>
            </label>
            <button
              onClick={handleGenerate}
              disabled={loading || (Object.keys(selections).length === 0 && !includeTemplate)}
              className="btn btn-primary btn-block mt-3"
            >
              {loading ? "Generating..." : "Generate shopping list"}
            </button>
          </div>

          <div className="mt-3">
            <button onClick={() => setEditLayout(!editLayout)} className="btn btn-ghost btn-sm">
              {editLayout ? "Close store layout" : "Edit store layout →"}
            </button>
            {editLayout && (
              <div className="card-soft mt-2">
                <p className="tiny muted" style={{ margin: "0 0 8px" }}>
                  Order items match on your list. Arrange to match your store's aisles.
                </p>
                <div className="col-2">
                  {layout.map((cat, i) => (
                    <div key={cat} className="row gap-2" style={{ padding: 2 }}>
                      <span className="muted tiny" style={{ width: 24 }}>{i + 1}.</span>
                      <span className="flex-1 small">{cat}</span>
                      <button onClick={() => moveCategory(i, -1)} disabled={i === 0} className="btn btn-xs">↑</button>
                      <button onClick={() => moveCategory(i, 1)} disabled={i === layout.length - 1} className="btn btn-xs">↓</button>
                    </div>
                  ))}
                  <button onClick={saveLayout} className="btn btn-primary btn-sm mt-2">Save layout</button>
                </div>
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
              {visibleCategories.length === 0 && <div className="empty">No items.</div>}
              {visibleCategories.map((cat) => (
                <div key={cat.category} className="mb-4">
                  <div className="shop-cat-header">
                    <span>{cat.category}</span>
                    <span className="shop-cat-count">{cat.items.length}</span>
                  </div>
                  {cat.items.map((item) => {
                    const isChecked = checked.has(item.fdc_id);
                    const fromTemplate = item.source === "template" || item.source === "both";
                    return (
                      <label
                        key={item.fdc_id}
                        className={`shop-row ${isChecked ? "checked" : ""}`}
                        style={fromTemplate ? { borderLeft: "3px solid var(--sage, #6b8e23)", paddingLeft: 8 } : undefined}
                      >
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={() => toggleChecked(item.fdc_id)}
                        />
                        <span className="flex-1">
                          {item.name}
                          {fromTemplate && (
                            <span
                              className="tiny muted"
                              style={{ marginLeft: 6 }}
                              title={item.source === "both" ? "From template + recipes" : "From household template"}
                            >
                              ★
                            </span>
                          )}
                          {item.note && (
                            <span className="tiny muted" style={{ marginLeft: 8 }}>— {item.note}</span>
                          )}
                        </span>
                        {editingQty === item.fdc_id ? (
                          <label className="field" onClick={(e) => e.preventDefault()}>
                            <input
                              type="number"
                              min={0}
                              step="any"
                              autoFocus
                              className="input input-num"
                              value={editDraft}
                              onChange={(e) => setEditDraft(e.target.value)}
                              onBlur={() => {
                                const v = Number(editDraft);
                                if (v > 0) {
                                  setQtyOverride((prev) => ({ ...prev, [item.fdc_id]: v }));
                                }
                                setEditingQty(null);
                              }}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                                if (e.key === "Escape") { setEditingQty(null); }
                              }}
                            />
                            <span className="tiny">{item.display_unit}</span>
                          </label>
                        ) : (
                          <span
                            className={`shop-qty ${isChecked ? "checked" : ""}`}
                            onClick={(e) => {
                              e.preventDefault();
                              const current = qtyOverride[item.fdc_id] ?? item.display_quantity;
                              setEditDraft(String(current));
                              setEditingQty(item.fdc_id);
                            }}
                            style={{ cursor: "pointer" }}
                            title="Click to alter quantity for this week"
                          >
                            {qtyOverride[item.fdc_id] ?? item.display_quantity} {item.display_unit}
                            {qtyOverride[item.fdc_id] !== undefined && (
                              <span className="tiny muted" style={{ marginLeft: 4 }}>·edited</span>
                            )}
                          </span>
                        )}
                        {item.display_unit !== "g" && qtyOverride[item.fdc_id] === undefined && (
                          <span className="tiny muted">({Math.round(item.quantity_g)} g)</span>
                        )}
                        <button
                          type="button"
                          onClick={(e) => { e.preventDefault(); hideForWeek(item.fdc_id); }}
                          className="btn btn-ghost btn-xs"
                          title="Skip this week (won't change the template)"
                        >
                          ✕
                        </button>
                      </label>
                    );
                  })}
                </div>
              ))}
              {hiddenItems.length > 0 && (
                <div className="card-soft mt-3">
                  <div className="row between mb-2">
                    <strong className="small">Skipped this week ({hiddenItems.length})</strong>
                    <span className="tiny muted">won't affect the template</span>
                  </div>
                  <div className="col-2">
                    {hiddenItems.map((it) => (
                      <div key={it.fdc_id} className="row gap-2" style={{ alignItems: "center" }}>
                        <span className="flex-1 tiny muted" style={{ textDecoration: "line-through" }}>
                          {it.name} — {it.display_quantity} {it.display_unit}
                        </span>
                        <button onClick={() => restoreItem(it.fdc_id)} className="btn btn-ghost btn-xs">
                          Restore
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
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
