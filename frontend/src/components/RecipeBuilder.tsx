import { useEffect, useState, useCallback } from "react";
import {
  fetchIngredientCategories,
  fetchIngredients,
  fetchRecipes,
  createRecipe,
  updateRecipe,
  deleteRecipe,
  aggregateRecipe,
  generateRecipe,
  searchUsda,
  addToPantry,
  onDataChanged,
  type Ingredient,
  type Recipe,
  type RecipeNutrition,
  type UsdaSearchResult,
} from "../api";

interface RecipeItem {
  ingredient: Ingredient;
  quantity_g: number;
}

export default function RecipeBuilder() {
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [activeRecipeId, setActiveRecipeId] = useState<string | null>(null);

  const [recipeName, setRecipeName] = useState("Untitled Recipe");
  const [servings, setServings] = useState(4);
  const [items, setItems] = useState<RecipeItem[]>([]);
  const [nutrition, setNutrition] = useState<RecipeNutrition | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  const [instructions, setInstructions] = useState<string[]>([]);

  const [genPrompt, setGenPrompt] = useState("");
  const [generating, setGenerating] = useState(false);

  const [categories, setCategories] = useState<string[]>([]);
  const [allIngredients, setAllIngredients] = useState<Ingredient[]>([]);
  const [selectedCat, setSelectedCat] = useState("");
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");

  const [usdaOpen, setUsdaOpen] = useState(false);
  const [usdaQuery, setUsdaQuery] = useState("");
  const [usdaResults, setUsdaResults] = useState<UsdaSearchResult[]>([]);
  const [usdaLoading, setUsdaLoading] = useState(false);

  useEffect(() => {
    fetchIngredientCategories().then(setCategories).catch(() => {});
    fetchIngredients().then(setAllIngredients).catch((e) => setError(String(e)));
    loadRecipes();
  }, []);

  useEffect(() => {
    return onDataChanged((kind) => {
      if (kind === "*" || kind === "recipes") loadRecipes();
      if (kind === "*" || kind === "pantry") {
        fetchIngredients().then(setAllIngredients).catch(() => {});
        fetchIngredientCategories().then(setCategories).catch(() => {});
      }
    });
  }, []);

  useEffect(() => {
    if (items.length === 0) { setNutrition(null); return; }
    aggregateRecipe(items.map((i) => ({ fdc_id: i.ingredient.fdc_id, quantity_g: i.quantity_g })))
      .then(setNutrition)
      .catch(() => setNutrition(null));
  }, [items]);

  async function loadRecipes() {
    try { setRecipes(await fetchRecipes()); } catch {}
  }

  async function reloadPantry() {
    setAllIngredients(await fetchIngredients());
    setCategories(await fetchIngredientCategories());
  }

  const loadRecipeIntoEditor = useCallback((recipe: Recipe) => {
    setActiveRecipeId(recipe.id);
    setRecipeName(recipe.name);
    const loaded: RecipeItem[] = [];
    for (const ri of recipe.ingredients) {
      const ing = allIngredients.find((i) => i.fdc_id === ri.fdc_id);
      if (ing) loaded.push({ ingredient: ing, quantity_g: ri.quantity_g });
    }
    setItems(loaded);
    setInstructions(recipe.instructions ?? []);
    setServings(recipe.servings ?? 4);
    setDirty(false);
  }, [allIngredients]);

  function newRecipe() {
    setActiveRecipeId(null);
    setRecipeName("Untitled Recipe");
    setItems([]);
    setInstructions([]);
    setServings(4);
    setDirty(false);
  }

  async function handleGenerate() {
    if (!genPrompt.trim()) return;
    setGenerating(true);
    setError("");
    try {
      const gen = await generateRecipe(genPrompt.trim());
      setActiveRecipeId(null);
      setRecipeName(gen.name);
      setInstructions(gen.instructions);
      const loaded: RecipeItem[] = [];
      for (const gi of gen.ingredients) {
        const ing = allIngredients.find((i) => i.fdc_id === gi.fdc_id);
        if (ing) loaded.push({ ingredient: ing, quantity_g: gi.quantity_g });
      }
      setItems(loaded);
      setDirty(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setGenerating(false);
    }
  }

  async function saveRecipe() {
    setSaving(true);
    try {
      const ingredients = items.map((i) => ({ fdc_id: i.ingredient.fdc_id, quantity_g: i.quantity_g }));
      if (activeRecipeId) {
        await updateRecipe(activeRecipeId, { name: recipeName, ingredients, instructions, servings });
      } else {
        const created = await createRecipe(recipeName, ingredients, instructions, servings);
        setActiveRecipeId(created.id);
      }
      setDirty(false);
      await loadRecipes();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteRecipe(id);
      if (activeRecipeId === id) newRecipe();
      await loadRecipes();
    } catch (e) { setError(String(e)); }
  }

  async function handleUsdaSearch() {
    if (usdaQuery.trim().length < 2) return;
    setUsdaLoading(true);
    try { setUsdaResults(await searchUsda(usdaQuery.trim())); }
    catch (e) { setError(String(e)); }
    finally { setUsdaLoading(false); }
  }

  async function promoteToPantry(r: UsdaSearchResult) {
    try {
      await addToPantry(r.fdc_id, undefined, r.mapped_category);
      await reloadPantry();
      setUsdaResults((prev) =>
        prev.map((x) => (x.fdc_id === r.fdc_id ? { ...x, in_pantry: true } : x))
      );
    } catch (e) { setError(String(e)); }
  }

  function markDirty() { setDirty(true); }

  const filtered = allIngredients.filter((ing) => {
    if (selectedCat && ing.food_group !== selectedCat) return false;
    if (search && !ing.name.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  function addItem(ingredient: Ingredient) {
    if (items.some((i) => i.ingredient.fdc_id === ingredient.fdc_id)) return;
    setItems((prev) => [...prev, { ingredient, quantity_g: 100 }]);
    markDirty();
  }

  function updateQuantity(fdcId: number, qty: number) {
    setItems((prev) =>
      prev.map((i) => (i.ingredient.fdc_id === fdcId ? { ...i, quantity_g: qty } : i))
    );
    markDirty();
  }

  function removeItem(fdcId: number) {
    setItems((prev) => prev.filter((i) => i.ingredient.fdc_id !== fdcId));
    markDirty();
  }

  return (
    <div className="col gap-5">
      <div className="hero">
        <h1>Build a recipe</h1>
        <p>Pick ingredients from your pantry, or describe a dish and let the kitchen think it up for you.</p>
      </div>

      {error && <div className="error">{error}</div>}

      {/* Saved recipes */}
      <div className="col gap-2">
        <h3 className="muted small" style={{ textTransform: "uppercase", letterSpacing: "0.05em", margin: 0 }}>
          Your recipes
        </h3>
        <div className="row wrap gap-2">
          <button onClick={newRecipe} className="btn btn-primary btn-sm">+ New recipe</button>
          {recipes.map((r) => (
            <span key={r.id} className={`chip ${r.id === activeRecipeId ? "chip-active" : ""}`}>
              <span onClick={() => loadRecipeIntoEditor(r)}>{r.name}</span>
              <span className="chip-x" onClick={(e) => { e.stopPropagation(); handleDelete(r.id); }}>×</span>
            </span>
          ))}
          {recipes.length === 0 && <span className="muted small">No saved recipes yet.</span>}
        </div>
      </div>

      {/* AI generation */}
      <div className="card-warm">
        <div className="row gap-3">
          <div style={{ fontSize: 22 }}>✦</div>
          <div className="flex-1 col-2">
            <strong style={{ fontFamily: "var(--font-serif)", fontSize: 16 }}>Generate a recipe</strong>
            <span className="small muted">Try "Thai red curry for 4" or "quick weeknight pasta with what's in season"</span>
          </div>
        </div>
        <div className="row gap-2 mt-3">
          <input
            className="input"
            placeholder="What are we cooking?"
            value={genPrompt}
            onChange={(e) => setGenPrompt(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !generating && handleGenerate()}
            disabled={generating}
          />
          <button
            onClick={handleGenerate}
            disabled={generating || !genPrompt.trim()}
            className="btn btn-accent"
          >
            {generating ? "Thinking..." : "Generate"}
          </button>
        </div>
      </div>

      {/* Editor: name, servings, save */}
      <div className="card">
        <div className="row gap-3 wrap">
          <input
            className="input-title flex-1"
            value={recipeName}
            onChange={(e) => { setRecipeName(e.target.value); markDirty(); }}
          />
          <label className="field">
            Servings
            <input
              type="number"
              min={1}
              className="input input-num"
              value={servings}
              onChange={(e) => { setServings(Math.max(1, Number(e.target.value) || 1)); markDirty(); }}
            />
          </label>
          <button
            onClick={saveRecipe}
            disabled={saving || (!dirty && activeRecipeId !== null)}
            className="btn btn-primary"
          >
            {saving ? "Saving..." : activeRecipeId ? "Save" : "Create"}
          </button>
        </div>

        <div className="divider" />

        <div className="row gap-5" style={{ alignItems: "flex-start", flexWrap: "wrap" }}>
          {/* Left: pantry picker */}
          <div className="flex-1" style={{ minWidth: 320 }}>
            <div className="row between mb-2">
              <h3 style={{ margin: 0 }}>Pantry</h3>
              <button onClick={() => setUsdaOpen(!usdaOpen)} className="btn btn-ghost btn-sm">
                {usdaOpen ? "Close USDA" : "+ Find more"}
              </button>
            </div>

            {usdaOpen && (
              <div className="card-soft mb-3">
                <div className="row gap-2 mb-2">
                  <input
                    className="input"
                    placeholder="Search USDA — cod, feta, tahini..."
                    value={usdaQuery}
                    onChange={(e) => setUsdaQuery(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleUsdaSearch()}
                  />
                  <button onClick={handleUsdaSearch} disabled={usdaLoading} className="btn btn-sm">
                    {usdaLoading ? "..." : "Search"}
                  </button>
                </div>
                <div className="scroll-y maxh-360">
                  {usdaResults.map((r) => (
                    <div key={r.fdc_id} className="list-row">
                      <div className="flex-1">
                        <div>{r.name}</div>
                        <div className="tiny muted">→ {r.mapped_category}{r.food_group ? ` · ${r.food_group}` : ""}</div>
                      </div>
                      <button
                        onClick={() => promoteToPantry(r)}
                        disabled={r.in_pantry}
                        className="btn btn-xs"
                      >
                        {r.in_pantry ? "✓ In pantry" : "+ Add"}
                      </button>
                    </div>
                  ))}
                  {usdaResults.length === 0 && usdaQuery && !usdaLoading && (
                    <p className="muted small mt-2">No results — press Search.</p>
                  )}
                </div>
              </div>
            )}

            <div className="row gap-2 mb-3">
              <select
                className="select"
                value={selectedCat}
                onChange={(e) => setSelectedCat(e.target.value)}
                style={{ width: "auto" }}
              >
                <option value="">All categories</option>
                {categories.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <input
                className="input flex-1"
                placeholder="Filter by name..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>

            <div className="list scroll-y maxh-480">
              {filtered.map((ing) => {
                const added = items.some((i) => i.ingredient.fdc_id === ing.fdc_id);
                return (
                  <div key={ing.fdc_id} className={`list-row ${added ? "disabled" : ""}`}>
                    <div className="flex-1">
                      <div style={{ fontWeight: 500 }}>{ing.name}</div>
                      <div className="tiny muted">{ing.energy_kcal_100g ?? "?"} kcal · {ing.proteins_100g ?? "?"}g protein /100g</div>
                    </div>
                    <button onClick={() => addItem(ing)} disabled={added} className="btn btn-xs">
                      {added ? "Added" : "+"}
                    </button>
                  </div>
                );
              })}
              {filtered.length === 0 && <div className="empty">No ingredients match.</div>}
            </div>
          </div>

          {/* Right: current recipe */}
          <div className="flex-1" style={{ minWidth: 320 }}>
            <h3>Ingredients <span className="muted small">({items.length})</span></h3>
            {items.length === 0 && (
              <div className="empty">Pick ingredients from your pantry.</div>
            )}

            <div className="col-2">
              {items.map((item) => (
                <div key={item.ingredient.fdc_id} className="row gap-2" style={{
                  background: "var(--cream-2)", padding: "8px 12px", borderRadius: "var(--r-sm)",
                }}>
                  <div className="flex-1" style={{ fontWeight: 500 }}>{item.ingredient.name}</div>
                  <input
                    type="number"
                    className="input input-num"
                    value={item.quantity_g}
                    onChange={(e) => updateQuantity(item.ingredient.fdc_id, Number(e.target.value) || 0)}
                    min={0}
                  />
                  <span className="small muted">g</span>
                  <button onClick={() => removeItem(item.ingredient.fdc_id)} className="icon-btn">×</button>
                </div>
              ))}
            </div>

            {nutrition && (
              <div className="card-accent mt-4">
                <h4>Nutrition</h4>
                <table className="table" style={{ background: "transparent" }}>
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
                      <tr key={String(label)}>
                        <td>{label}</td>
                        <td className="right" style={{ fontWeight: 600 }}>{val} {unit}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {nutrition.items_missing.length > 0 && (
                  <p className="small mt-2" style={{ color: "var(--terracotta-dark)" }}>
                    Missing data for some items.
                  </p>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Instructions */}
        <div className="divider" />
        <div className="col-2">
          <div className="row between">
            <h3 style={{ margin: 0 }}>Instructions</h3>
            <button
              onClick={() => { setInstructions((prev) => [...prev, ""]); markDirty(); }}
              className="btn btn-sm"
            >
              + Step
            </button>
          </div>
          {instructions.length === 0 && (
            <div className="empty">No steps yet — add one or generate a recipe.</div>
          )}
          <ol className="col-2" style={{ paddingLeft: 24, margin: 0 }}>
            {instructions.map((step, i) => (
              <li key={i} className="row gap-2" style={{ alignItems: "flex-start" }}>
                <textarea
                  className="textarea flex-1"
                  value={step}
                  onChange={(e) => {
                    const next = [...instructions]; next[i] = e.target.value;
                    setInstructions(next); markDirty();
                  }}
                  rows={1}
                />
                <button
                  onClick={() => { setInstructions((prev) => prev.filter((_, j) => j !== i)); markDirty(); }}
                  className="icon-btn"
                >×</button>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </div>
  );
}
