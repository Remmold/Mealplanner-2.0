import { useEffect, useLayoutEffect, useMemo, useRef, useState, useCallback } from "react";
import { ChefHat, Check, Plus, RefreshCw, Sparkles, X } from "lucide-react";
import CookMode from "./CookMode";
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
  regenerateRecipeImage,
  type Ingredient,
  type Recipe,
  type RecipeNutrition,
  type UsdaSearchResult,
} from "../api";
import {
  Button, Card, Chip, Divider, Empty, ErrorBanner, Field, IconButton,
  Input, List, ListRow, Select, Textarea,
} from "./ui";

interface RecipeItem {
  ingredient: Ingredient;
  quantity_g: number;
}

interface RecipeBuilderProps {
  initialRecipeId?: string | null;
  onInitialConsumed?: () => void;
}

export default function RecipeBuilder({ initialRecipeId, onInitialConsumed }: RecipeBuilderProps = {}) {
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [activeRecipeId, setActiveRecipeId] = useState<string | null>(null);

  const [recipeName, setRecipeName] = useState("Untitled Recipe");
  const [servings, setServings] = useState(4);
  const [imagePath, setImagePath] = useState<string | null>(null);
  const [imageBust, setImageBust] = useState(0);    // force <img> reload after regenerate
  const [regenerating, setRegenerating] = useState(false);
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

  const [cookOpen, setCookOpen] = useState(false);

  // Build a Recipe-shaped snapshot of the editor state for CookMode.
  // Uses current editor values so the cook view reflects unsaved tweaks.
  const cookRecipe = useMemo<Recipe>(() => ({
    id: activeRecipeId ?? "",
    household_id: "",
    name: recipeName,
    ingredients: items.map((it) => ({
      fdc_id: it.ingredient.fdc_id,
      quantity_g: it.quantity_g,
      ingredient_name: it.ingredient.name,
    })),
    instructions,
    servings,
    image_path: imagePath,
    created_at: "",
    updated_at: "",
  }), [activeRecipeId, recipeName, items, instructions, servings, imagePath]);

  useEffect(() => {
    fetchIngredientCategories().then(setCategories).catch(() => {});
    fetchIngredients().then(setAllIngredients).catch((e) => setError(String(e)));
    loadRecipes();
  }, []);

  // Auto-select a recipe when the parent passes initialRecipeId (navigation from chat).
  useEffect(() => {
    if (!initialRecipeId) return;
    const hit = recipes.find((r) => r.id === initialRecipeId);
    if (hit) {
      loadRecipeIntoEditor(hit);
      onInitialConsumed?.();
    } else {
      // Not in our list yet (fresh from chat). Refresh once.
      loadRecipes();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialRecipeId, recipes]);

  useEffect(() => {
    return onDataChanged((kind) => {
      if (kind === "*" || kind === "recipes") loadRecipes();
      if (kind === "*" || kind === "pantry") {
        fetchIngredients().then(setAllIngredients).catch(() => {});
        fetchIngredientCategories().then(setCategories).catch(() => {});
      }
    });
  }, []);

  // While viewing a recipe without an image yet, poll every 5s to pick up the
  // background-generated one.
  useEffect(() => {
    if (!activeRecipeId || imagePath) return;
    const id = setInterval(() => { loadRecipes(); }, 5000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRecipeId, imagePath]);

  useEffect(() => {
    if (items.length === 0) { setNutrition(null); return; }
    aggregateRecipe(items.map((i) => ({ fdc_id: i.ingredient.fdc_id, quantity_g: i.quantity_g })))
      .then(setNutrition)
      .catch(() => setNutrition(null));
  }, [items]);

  async function loadRecipes() {
    try {
      const list = await fetchRecipes();
      setRecipes(list);
      if (activeRecipeId) {
        const cur = list.find((r) => r.id === activeRecipeId);
        if (cur && cur.image_path !== imagePath) {
          setImagePath(cur.image_path ?? null);
          setImageBust(Date.now());
        }
      }
    } catch {}
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
    setImagePath(recipe.image_path ?? null);
    setImageBust(Date.now());
    setDirty(false);
  }, [allIngredients]);

  function newRecipe() {
    setActiveRecipeId(null);
    setRecipeName("Untitled Recipe");
    setItems([]);
    setInstructions([]);
    setServings(4);
    setImagePath(null);
    setDirty(false);
  }

  async function handleRegenerateImage() {
    if (!activeRecipeId) return;
    setRegenerating(true);
    try {
      await regenerateRecipeImage(activeRecipeId);
      await loadRecipes();
      // Find the updated recipe and refresh our local image_path
      setImageBust(Date.now());
    } catch (e) { setError(String(e)); }
    finally { setRegenerating(false); }
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

      <ErrorBanner>{error}</ErrorBanner>

      {/* Saved recipes */}
      <div className="col gap-2">
        <h3 className="muted small overline m-0">Your recipes</h3>
        <div className="row wrap gap-2">
          <Button onClick={newRecipe} variant="primary" size="sm"><Plus size={14} /> New recipe</Button>
          {recipes.map((r) => (
            <Chip
              key={r.id}
              active={r.id === activeRecipeId}
              onClick={() => loadRecipeIntoEditor(r)}
              onRemove={() => handleDelete(r.id)}
            >
              {r.name}
            </Chip>
          ))}
          {recipes.length === 0 && <span className="muted small">No saved recipes yet.</span>}
        </div>
      </div>

      {/* AI generation */}
      <Card variant="warm">
        <div className="row gap-3">
          <Sparkles size={22} />
          <div className="flex-1 col-2">
            <h4 className="m-0">Generate a recipe</h4>
            <span className="small muted">Try "Thai red curry for 4" or "quick weeknight pasta with what's in season"</span>
          </div>
        </div>
        <div className="row gap-2 mt-3">
          <Input
            placeholder="What are we cooking?"
            value={genPrompt}
            onChange={(e) => setGenPrompt(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !generating && handleGenerate()}
            disabled={generating}
          />
          <Button onClick={handleGenerate} disabled={generating || !genPrompt.trim()} variant="accent">
            {generating ? "Thinking..." : "Generate"}
          </Button>
        </div>
      </Card>

      {/* Editor: name, servings, save */}
      <Card>
        {activeRecipeId && (
          <div className="recipe-hero">
            {imagePath ? (
              <img
                src={`/api/recipe-images/${imagePath}?v=${imageBust}`}
                alt={recipeName}
                className="recipe-hero-img"
              />
            ) : (
              <div className="recipe-hero-placeholder">
                <span className="tiny muted">Generating image…</span>
              </div>
            )}
            <Button
              onClick={handleRegenerateImage}
              disabled={regenerating}
              size="xs"
              className="recipe-hero-regen"
              title="Generate a new image"
            >
              {regenerating ? "…" : <><RefreshCw size={12} /> Regenerate image</>}
            </Button>
          </div>
        )}
        <div className="row gap-3 wrap">
          <Input
            variant="title"
            className="flex-1"
            value={recipeName}
            onChange={(e) => { setRecipeName(e.target.value); markDirty(); }}
          />
          <Field>
            Servings
            <Input
              type="number"
              min={1}
              numeric
              value={servings}
              onChange={(e) => { setServings(Math.max(1, Number(e.target.value) || 1)); markDirty(); }}
            />
          </Field>
          <Button onClick={saveRecipe} disabled={saving || (!dirty && activeRecipeId !== null)} variant="primary">
            {saving ? "Saving..." : activeRecipeId ? "Save" : "Create"}
          </Button>
          <Button
            onClick={() => setCookOpen(true)}
            disabled={items.length === 0 && instructions.length === 0}
            variant="accent"
            title="Open step-by-step cook mode"
          >
            <ChefHat size={14} />
            <span className="ml-1">Start cooking</span>
          </Button>
        </div>

        <Divider />

        <div className="row gap-5 wrap items-start">
          {/* Left: pantry picker */}
          <div className="flex-1 min-w-320">
            <div className="row between mb-2">
              <h3 className="m-0">Pantry</h3>
              <Button onClick={() => setUsdaOpen(!usdaOpen)} variant="ghost" size="sm">
                {usdaOpen ? "Close USDA" : <><Plus size={14} /> Find more</>}
              </Button>
            </div>

            {usdaOpen && (
              <Card variant="soft" className="mb-3">
                <div className="row gap-2 mb-2">
                  <Input
                    placeholder="Search USDA — cod, feta, tahini..."
                    value={usdaQuery}
                    onChange={(e) => setUsdaQuery(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleUsdaSearch()}
                  />
                  <Button onClick={handleUsdaSearch} disabled={usdaLoading} size="sm">
                    {usdaLoading ? "..." : "Search"}
                  </Button>
                </div>
                <div className="scroll-y maxh-360">
                  {usdaResults.map((r) => (
                    <ListRow key={r.fdc_id}>
                      <div className="flex-1">
                        <div>{r.name}</div>
                        <div className="tiny muted">→ {r.mapped_category}{r.food_group ? ` · ${r.food_group}` : ""}</div>
                      </div>
                      <Button onClick={() => promoteToPantry(r)} disabled={r.in_pantry} size="xs">
                        {r.in_pantry ? <><Check size={12} /> In pantry</> : <><Plus size={12} /> Add</>}
                      </Button>
                    </ListRow>
                  ))}
                  {usdaResults.length === 0 && usdaQuery && !usdaLoading && (
                    <p className="muted small mt-2">No results — press Search.</p>
                  )}
                </div>
              </Card>
            )}

            <div className="row gap-2 mb-3">
              <Select
                className="w-auto"
                value={selectedCat}
                onChange={(e) => setSelectedCat(e.target.value)}
              >
                <option value="">All categories</option>
                {categories.map((c) => <option key={c} value={c}>{c}</option>)}
              </Select>
              <Input
                className="flex-1"
                placeholder="Filter by name..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>

            <List className="scroll-y maxh-480">
              {filtered.map((ing) => {
                const added = items.some((i) => i.ingredient.fdc_id === ing.fdc_id);
                return (
                  <ListRow key={ing.fdc_id} disabled={added}>
                    <div className="flex-1">
                      <div className="fw-500">{ing.name}</div>
                      <div className="tiny muted">{ing.energy_kcal_100g ?? "?"} kcal · {ing.proteins_100g ?? "?"}g protein /100g</div>
                    </div>
                    <Button onClick={() => addItem(ing)} disabled={added} size="xs">
                      {added ? "Added" : <Plus size={14} />}
                    </Button>
                  </ListRow>
                );
              })}
              {filtered.length === 0 && <Empty>No ingredients match.</Empty>}
            </List>
          </div>

          {/* Right: current recipe */}
          <div className="flex-1 min-w-320">
            <h3>Ingredients <span className="muted small">({items.length})</span></h3>
            {items.length === 0 && (
              <Empty>Pick ingredients from your pantry.</Empty>
            )}

            <div className="col-2">
              {items.map((item) => (
                <div key={item.ingredient.fdc_id} className="row gap-2 inset">
                  <div className="flex-1 fw-500">{item.ingredient.name}</div>
                  <Input
                    type="number"
                    numeric
                    value={item.quantity_g}
                    onChange={(e) => updateQuantity(item.ingredient.fdc_id, Number(e.target.value) || 0)}
                    min={0}
                  />
                  <span className="small muted">g</span>
                  <IconButton onClick={() => removeItem(item.ingredient.fdc_id)} aria-label="Remove">
                    <X size={14} />
                  </IconButton>
                </div>
              ))}
            </div>

            {nutrition && (
              <Card variant="accent" className="mt-4">
                <h4>Nutrition</h4>
                <table className="table">
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
                        <td className="right fw-600">{val} {unit}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {nutrition.items_missing.length > 0 && (
                  <p className="small mt-2 text-warm">
                    Missing data for some items.
                  </p>
                )}
              </Card>
            )}
          </div>
        </div>

        {/* Instructions */}
        <Divider />
        <div className="col-2">
          <div className="row between">
            <h3 className="m-0">Instructions</h3>
            <Button
              onClick={() => { setInstructions((prev) => [...prev, ""]); markDirty(); }}
              size="sm"
            >
              <Plus size={14} /> Step
            </Button>
          </div>
          {instructions.length === 0 && (
            <Empty>No steps yet — add one or generate a recipe.</Empty>
          )}
          <ol className="col-2 m-0 pl-24">
            {instructions.map((step, i) => (
              <li key={i} className="row gap-2 items-start">
                <AutoGrowTextarea
                  className="flex-1"
                  value={step}
                  onChange={(v) => {
                    const next = [...instructions]; next[i] = v;
                    setInstructions(next); markDirty();
                  }}
                />
                <IconButton
                  onClick={() => { setInstructions((prev) => prev.filter((_, j) => j !== i)); markDirty(); }}
                  aria-label="Remove step"
                >
                  <X size={14} />
                </IconButton>
              </li>
            ))}
          </ol>
        </div>
      </Card>

      <CookMode
        open={cookOpen}
        recipe={cookRecipe}
        onClose={() => setCookOpen(false)}
      />
    </div>
  );
}

/** Textarea that grows to fit its content. */
function AutoGrowTextarea({
  value, onChange, className,
}: {
  value: string;
  onChange: (v: string) => void;
  className?: string;
}) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);
  return (
    <Textarea
      ref={ref}
      className={["textarea-autogrow", className].filter(Boolean).join(" ")}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      rows={1}
    />
  );
}
