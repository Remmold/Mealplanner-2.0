import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
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
import { useEnumLabels } from "../i18n/enums";

interface Selection { recipe: Recipe; portions: number; }

type View = "list" | "template";

// Persist the generated list + which items are ticked / skipped / qty-edited to
// localStorage, so checking items off survives reloads and leaving the Shopping tab
// (this component unmounts on tab switch, which is why state otherwise resets).
// Per-device only — not synced across household members.
const STORAGE_KEY = "mealplanner.shoppingList.v1";

interface PersistedShopping {
  list: ShoppingListType | null;
  checked: number[];
  hidden: number[];
  qtyOverride: Record<number, number>;
}

function loadPersistedShopping(): PersistedShopping | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as PersistedShopping) : null;
  } catch {
    return null;
  }
}

export default function ShoppingList() {
  const { t } = useTranslation();
  const el = useEnumLabels();
  const [view, setView] = useState<View>("list");

  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [selections, setSelections] = useState<Record<string, Selection>>({});
  const [persisted] = useState(loadPersistedShopping);
  const [list, setList] = useState<ShoppingListType | null>(persisted?.list ?? null);
  const [checked, setChecked] = useState<Set<number>>(new Set(persisted?.checked ?? []));
  // Items the user removed *just for this week*. Persisted per-device with the list.
  const [hidden, setHidden] = useState<Set<number>>(new Set(persisted?.hidden ?? []));
  // Per-week display-quantity overrides (fdc_id -> edited display_quantity, unit
  // unchanged). Persisted per-device with the list; cleared on regenerate.
  const [qtyOverride, setQtyOverride] = useState<Record<number, number>>(persisted?.qtyOverride ?? {});
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

  // Persist the list + ticks / skips / qty-edits so they survive reloads and
  // leaving the Shopping tab (this component unmounts on tab switch).
  useEffect(() => {
    try {
      if (!list) {
        localStorage.removeItem(STORAGE_KEY);
        return;
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        list, checked: [...checked], hidden: [...hidden], qtyOverride,
      }));
    } catch {
      /* ignore quota / serialization errors */
    }
  }, [list, checked, hidden, qtyOverride]);

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
            <h2 className="m-0">{t("shopping.templateHeading")}</h2>
            <span className="small muted">
              {t("shopping.templateSubtitle")}
            </span>
          </div>
          <Button onClick={() => setView("list")} variant="ghost" size="sm">
            <ArrowLeft size={14} /> {t("shopping.backToList")}
          </Button>
        </div>
        <ShoppingTemplate />
      </div>
    );
  }

  return (
    <div className="col gap-5">
      <div className="hero">
        <h1>{t("shopping.heading")}</h1>
        <p>{t("shopping.intro")}</p>
      </div>

      <div className="row gap-2">
        <Button onClick={() => setView("template")} variant="ghost" size="sm">
          {t("shopping.manageTemplate")} <ArrowRight size={14} />
        </Button>
      </div>

      <ErrorBanner>{error}</ErrorBanner>

      <div className="row gap-5 wrap items-start">
        {/* Left: pick recipes */}
        <div className="flex-1 min-w-320">
          <Card>
            <div className="row between mb-2 items-baseline">
              <h4 className="m-0">{t("shopping.pickRecipes")}</h4>
              <span className="tiny muted">
                {t("shopping.selectedTotal", { selected: Object.keys(selections).length, total: recipes.length })}
              </span>
            </div>
            {recipes.length === 0 ? (
              <Empty>{t("shopping.noRecipes")}</Empty>
            ) : (
              <>
                <Input
                  className="mb-2"
                  placeholder={t("shopping.filterPlaceholder")}
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
                              <span className="tiny">{t("shopping.portionsAbbrev")}</span>
                            </Field>
                          ) : (
                            <span className="tiny muted">{t("shopping.servingsAbbrev", { count: r.servings })}</span>
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
              <span className="small">{t("shopping.includeTemplate")}</span>
            </label>
            <Button
              onClick={handleGenerate}
              disabled={loading || (Object.keys(selections).length === 0 && !includeTemplate)}
              variant="primary"
              block
              className="mt-3"
            >
              {loading ? t("common.generating") : t("shopping.generate")}
            </Button>
          </Card>

          <div className="mt-3">
            <Button onClick={() => setEditLayout(!editLayout)} variant="ghost" size="sm">
              {editLayout ? t("shopping.closeStoreLayout") : <>{t("shopping.editStoreLayout")} <ArrowRight size={14} /></>}
            </Button>
            {editLayout && (
              <Card variant="soft" className="mt-2">
                <p className="tiny muted mb-2">
                  {t("shopping.layoutHint")}
                </p>
                <div className="col-2">
                  {layout.map((cat, i) => (
                    <div key={cat} className="row gap-2">
                      <span className="muted tiny w-24">{i + 1}.</span>
                      <span className="flex-1 small">{el.category(cat)}</span>
                      <Button onClick={() => moveCategory(i, -1)} disabled={i === 0} size="xs" aria-label={t("shopping.moveUp")}>
                        <ArrowUp size={14} />
                      </Button>
                      <Button onClick={() => moveCategory(i, 1)} disabled={i === layout.length - 1} size="xs" aria-label={t("shopping.moveDown")}>
                        <ArrowDown size={14} />
                      </Button>
                    </div>
                  ))}
                  <Button onClick={saveLayout} variant="primary" size="sm" className="mt-2">{t("shopping.saveLayout")}</Button>
                </div>
              </Card>
            )}
          </div>
        </div>

        {/* Right: generated list */}
        <div className="flex-1 min-w-320">
          {!list && <Card className="empty">{t("shopping.noListYet")}</Card>}
          {list && (
            <Card>
              <div className="row between mb-3">
                <h3 className="m-0">{t("shopping.yourList")}</h3>
                <Pill>{t("shopping.doneCount", { checked: checkedCount, total: totalItems })}</Pill>
              </div>
              {visibleCategories.length === 0 && <Empty>{t("shopping.noItems")}</Empty>}
              {visibleCategories.map((cat) => (
                <div key={cat.category} className="mb-4">
                  <div className="shop-cat-header">
                    <span>{el.category(cat.category)}</span>
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
                          {el.ingredient(item.fdc_id, item.name)}
                          {fromTemplate && (
                            <span
                              className="ml-1"
                              title={item.source === "both" ? t("shopping.fromTemplateAndRecipes") : t("shopping.fromHouseholdTemplate")}
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
                            <span className="tiny">{el.unit(item.display_unit)}</span>
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
                            title={t("shopping.clickToAlterQty")}
                          >
                            {qtyOverride[item.fdc_id] ?? item.display_quantity} {el.unit(item.display_unit)}
                            {qtyOverride[item.fdc_id] !== undefined && (
                              <span className="tiny muted ml-1">{t("shopping.editedTag")}</span>
                            )}
                          </span>
                        )}
                        {item.display_unit !== "g" && qtyOverride[item.fdc_id] === undefined && (
                          <span className="tiny muted">{t("shopping.approxGrams", { grams: Math.round(item.quantity_g) })}</span>
                        )}
                        <Button
                          type="button"
                          onClick={(e) => { e.preventDefault(); hideForWeek(item.fdc_id); }}
                          variant="ghost"
                          size="xs"
                          title={t("shopping.skipThisWeekTitle")}
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
                    <strong className="small">{t("shopping.skippedThisWeek", { count: hiddenItems.length })}</strong>
                    <span className="tiny muted">{t("shopping.wontAffectTemplate")}</span>
                  </div>
                  <div className="col-2">
                    {hiddenItems.map((it) => (
                      <div key={it.fdc_id} className="row gap-2">
                        <span className="flex-1 tiny muted line-through">
                          {el.ingredient(it.fdc_id, it.name)} — {it.display_quantity} {el.unit(it.display_unit)}
                        </span>
                        <Button onClick={() => restoreItem(it.fdc_id)} variant="ghost" size="xs">
                          {t("shopping.restore")}
                        </Button>
                      </div>
                    ))}
                  </div>
                </Card>
              )}
              {list.missing_recipes.length > 0 && (
                <p className="small text-warm">
                  {t("shopping.recipesNotFound", { list: list.missing_recipes.join(", ") })}
                </p>
              )}
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
