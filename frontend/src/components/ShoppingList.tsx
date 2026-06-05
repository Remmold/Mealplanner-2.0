import { useEffect, useState } from "react";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Star, X } from "lucide-react";
import {
  fetchRecipes,
  generateShoppingList,
  fetchStoreLayout,
  updateStoreLayout,
  type Recipe,
  type ShoppingList as ShoppingListType,
} from "../api";
import ShoppingTemplate from "./ShoppingTemplate";
import { Button, Card, Empty, ErrorBanner, Field, Input, Pill } from "./ui";

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
        <div className="row between items-baseline">
          <div>
            <h2 className="m-0">Shopping template</h2>
            <span className="small muted">
              Baseline items — preprinted into every weekly list. Edits here are permanent.
            </span>
          </div>
          <Button onClick={() => setView("list")} variant="ghost" size="sm">
            <ArrowLeft size={14} /> Back to list
          </Button>
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
        <Button onClick={() => setView("template")} variant="ghost" size="sm">
          Manage shopping template <ArrowRight size={14} />
        </Button>
      </div>

      <ErrorBanner>{error}</ErrorBanner>

      <div className="row gap-5 wrap items-start">
        {/* Left: pick recipes */}
        <div className="flex-1 min-w-320">
          <Card>
            <div className="row between mb-2 items-baseline">
              <h4 className="m-0">Pick recipes</h4>
              <span className="tiny muted">
                {Object.keys(selections).length} selected · {recipes.length} total
              </span>
            </div>
            {recipes.length === 0 ? (
              <Empty>No recipes saved yet.</Empty>
            ) : (
              <>
                <Input
                  className="mb-2"
                  placeholder="Filter recipes…"
                  value={recipeFilter}
                  onChange={(e) => setRecipeFilter(e.target.value)}
                />
                <div className="scroll-box">
                  {recipes
                    .filter((r) => r.name.toLowerCase().includes(recipeFilter.toLowerCase()))
                    .map((r) => {
                      const sel = selections[r.id];
                      return (
                        <div
                          key={r.id}
                          onClick={() => toggleRecipe(r)}
                          className={`pick-row ${sel ? "selected" : ""}`}
                        >
                          <input
                            type="checkbox"
                            checked={!!sel}
                            onChange={() => toggleRecipe(r)}
                            onClick={(e) => e.stopPropagation()}
                          />
                          <span className={`flex-1 small ${sel ? "fw-500" : ""}`}>
                            {r.name}
                          </span>
                          {sel ? (
                            <Field onClick={(e) => e.stopPropagation()}>
                              <Input
                                type="number"
                                min={1}
                                numeric
                                value={sel.portions}
                                onChange={(e) => updatePortions(r.id, Number(e.target.value) || 1)}
                              />
                              <span className="tiny">pt</span>
                            </Field>
                          ) : (
                            <span className="tiny muted">{r.servings}s</span>
                          )}
                        </div>
                      );
                    })}
                </div>
              </>
            )}
            <label className="row gap-2 mt-2">
              <input
                type="checkbox"
                checked={includeTemplate}
                onChange={(e) => setIncludeTemplate(e.target.checked)}
              />
              <span className="small">Include household template (baseline items)</span>
            </label>
            <Button
              onClick={handleGenerate}
              disabled={loading || (Object.keys(selections).length === 0 && !includeTemplate)}
              variant="primary"
              block
              className="mt-3"
            >
              {loading ? "Generating..." : "Generate shopping list"}
            </Button>
          </Card>

          <div className="mt-3">
            <Button onClick={() => setEditLayout(!editLayout)} variant="ghost" size="sm">
              {editLayout ? "Close store layout" : <>Edit store layout <ArrowRight size={14} /></>}
            </Button>
            {editLayout && (
              <Card variant="soft" className="mt-2">
                <p className="tiny muted mb-2">
                  Order items match on your list. Arrange to match your store's aisles.
                </p>
                <div className="col-2">
                  {layout.map((cat, i) => (
                    <div key={cat} className="row gap-2">
                      <span className="muted tiny w-24">{i + 1}.</span>
                      <span className="flex-1 small">{cat}</span>
                      <Button onClick={() => moveCategory(i, -1)} disabled={i === 0} size="xs" aria-label="Move up">
                        <ArrowUp size={14} />
                      </Button>
                      <Button onClick={() => moveCategory(i, 1)} disabled={i === layout.length - 1} size="xs" aria-label="Move down">
                        <ArrowDown size={14} />
                      </Button>
                    </div>
                  ))}
                  <Button onClick={saveLayout} variant="primary" size="sm" className="mt-2">Save layout</Button>
                </div>
              </Card>
            )}
          </div>
        </div>

        {/* Right: generated list */}
        <div className="flex-1 min-w-320">
          {!list && <Card className="empty">No list yet — pick some recipes.</Card>}
          {list && (
            <Card>
              <div className="row between mb-3">
                <h3 className="m-0">Your list</h3>
                <Pill>{checkedCount} / {totalItems} done</Pill>
              </div>
              {visibleCategories.length === 0 && <Empty>No items.</Empty>}
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
                        className={`shop-row ${isChecked ? "checked" : ""} ${fromTemplate ? "from-template" : ""}`}
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
                              className="ml-1"
                              title={item.source === "both" ? "From template + recipes" : "From household template"}
                            >
                              <Star size={12} className="muted" />
                            </span>
                          )}
                          {item.note && (
                            <span className="tiny muted ml-2">— {item.note}</span>
                          )}
                        </span>
                        {editingQty === item.fdc_id ? (
                          <Field onClick={(e) => e.preventDefault()}>
                            <Input
                              type="number"
                              min={0}
                              step="any"
                              autoFocus
                              numeric
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
                          </Field>
                        ) : (
                          <span
                            className={`shop-qty clickable ${isChecked ? "checked" : ""}`}
                            onClick={(e) => {
                              e.preventDefault();
                              const current = qtyOverride[item.fdc_id] ?? item.display_quantity;
                              setEditDraft(String(current));
                              setEditingQty(item.fdc_id);
                            }}
                            title="Click to alter quantity for this week"
                          >
                            {qtyOverride[item.fdc_id] ?? item.display_quantity} {item.display_unit}
                            {qtyOverride[item.fdc_id] !== undefined && (
                              <span className="tiny muted ml-1">·edited</span>
                            )}
                          </span>
                        )}
                        {item.display_unit !== "g" && qtyOverride[item.fdc_id] === undefined && (
                          <span className="tiny muted">({Math.round(item.quantity_g)} g)</span>
                        )}
                        <Button
                          type="button"
                          onClick={(e) => { e.preventDefault(); hideForWeek(item.fdc_id); }}
                          variant="ghost"
                          size="xs"
                          title="Skip this week (won't change the template)"
                        >
                          <X size={14} />
                        </Button>
                      </label>
                    );
                  })}
                </div>
              ))}
              {hiddenItems.length > 0 && (
                <Card variant="soft" className="mt-3">
                  <div className="row between mb-2">
                    <strong className="small">Skipped this week ({hiddenItems.length})</strong>
                    <span className="tiny muted">won't affect the template</span>
                  </div>
                  <div className="col-2">
                    {hiddenItems.map((it) => (
                      <div key={it.fdc_id} className="row gap-2">
                        <span className="flex-1 tiny muted line-through">
                          {it.name} — {it.display_quantity} {it.display_unit}
                        </span>
                        <Button onClick={() => restoreItem(it.fdc_id)} variant="ghost" size="xs">
                          Restore
                        </Button>
                      </div>
                    ))}
                  </div>
                </Card>
              )}
              {list.missing_recipes.length > 0 && (
                <p className="small text-warm">
                  Some recipes not found: {list.missing_recipes.join(", ")}
                </p>
              )}
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
