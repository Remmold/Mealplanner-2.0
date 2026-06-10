import { useEffect, useLayoutEffect, useMemo, useRef, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useEnumLabels } from "../i18n/enums";
import {
  Apple, ArrowLeft, Beef, Carrot, Check, ChefHat, Droplet, Drumstick, Fish,
  Milk, Minus, Nut, Pencil, Plus, RefreshCw, Soup, Sparkles, UtensilsCrossed, Wheat, X,
} from "lucide-react";
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
  seedStarterRecipes,
  ensureIngredientImages,
  type Ingredient,
  type Recipe,
  type RecipeNutrition,
  type UsdaSearchResult,
} from "../api";
import {
  Button, Card, Divider, Empty, ErrorBanner, Field, IconButton,
  Input, List, ListRow, Pill, Select, Textarea,
} from "./ui";

interface RecipeItem {
  ingredient: Ingredient;
  quantity_g: number;
}

// Resolve a recipe ingredient to a full Ingredient. Curated-catalogue match wins;
// otherwise keep it as a minimal entry built from the name the API already sent.
// Without this, USDA-only ingredients (e.g. chicken breast) silently vanished from
// the recipe — and a later save would have persisted the truncated list.
function resolveIngredient(
  catalog: Ingredient[],
  fdc_id: number,
  fallbackName: string | null | undefined,
): Ingredient {
  const hit = catalog.find((i) => i.fdc_id === fdc_id);
  if (hit) return hit;
  return {
    fdc_id,
    name: fallbackName || `#${fdc_id}`,
    food_group: "",
    subcategory: null,
    energy_kcal_100g: null,
    proteins_100g: null,
    carbohydrates_100g: null,
    sugars_100g: null,
    fat_100g: null,
    saturated_fat_100g: null,
    fiber_100g: null,
    salt_100g: null,
  };
}

interface RecipeBuilderProps {
  initialRecipeId?: string | null;
  onInitialConsumed?: () => void;
}

export default function RecipeBuilder({ initialRecipeId, onInitialConsumed }: RecipeBuilderProps = {}) {
  const { t } = useTranslation();
  const el = useEnumLabels();
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [activeRecipeId, setActiveRecipeId] = useState<string | null>(null);

  const [recipeName, setRecipeName] = useState(t("recipe.untitledRecipe"));
  const [servings, setServings] = useState(4);
  // Recipe-view-only "scale to N people" — display amounts ×(viewServings/servings).
  // Not saved; the stored recipe stays at its base servings.
  const [viewServings, setViewServings] = useState(4);
  const [mealType, setMealType] = useState<"breakfast" | "lunch" | "dinner" | "">("");
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

  // Three surfaces: the cookbook "list", a read-only "view" of one recipe
  // (opened by clicking a card), and the "edit" form (opened by + Create, the
  // view's Edit button, or a successful AI generate). Default is the list.
  const [mode, setMode] = useState<"list" | "view" | "edit">("list");
  // Cookbook tab filter — "all" shows every recipe; otherwise a chapter key.
  const [activeChapter, setActiveChapter] = useState<string>("all");
  const [seeding, setSeeding] = useState(false);
  const [seedMessage, setSeedMessage] = useState<string | null>(null);

  async function handleSeedStarters() {
    setSeeding(true);
    setSeedMessage(null);
    try {
      const created = await seedStarterRecipes(12);
      if (created.length === 0) {
        setSeedMessage(t("recipe.seedNone"));
      } else {
        setSeedMessage(t("recipe.seedAdded", { count: created.length }));
        const next = await fetchRecipes();
        setRecipes(next);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSeeding(false);
    }
  }

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
    meal_type: mealType || null,
    image_path: imagePath,
    created_at: "",
    updated_at: "",
  }), [activeRecipeId, recipeName, items, instructions, servings, mealType, imagePath]);

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
      openRecipe(hit);
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

  // Open a saved recipe in the read-only view (clicking a card / chat deep link).
  const openRecipe = useCallback((recipe: Recipe) => {
    setActiveRecipeId(recipe.id);
    setRecipeName(recipe.name);
    const loaded: RecipeItem[] = recipe.ingredients.map((ri) => ({
      ingredient: resolveIngredient(allIngredients, ri.fdc_id, ri.ingredient_name),
      quantity_g: ri.quantity_g,
    }));
    setItems(loaded);
    setInstructions(recipe.instructions ?? []);
    setServings(recipe.servings ?? 4);
    setViewServings(recipe.servings ?? 4);
    setMealType(recipe.meal_type ?? "");
    setImagePath(recipe.image_path ?? null);
    setImageBust(Date.now());
    setDirty(false);
    // Lazily generate any missing ingredient icons for this recipe.
    void ensureIngredientImages(recipe.ingredients.map((ri) => ri.fdc_id));
    if (typeof window !== "undefined") window.scrollTo({ top: 0, behavior: "smooth" });
    setMode("view");
  }, [allIngredients]);

  function newRecipe() {
    setActiveRecipeId(null);
    setRecipeName(t("recipe.untitledRecipe"));
    setItems([]);
    setInstructions([]);
    setServings(4);
    setMealType("");
    setImagePath(null);
    setDirty(false);
    setMode("edit");
    if (typeof window !== "undefined") window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function backToList() {
    if (mode === "edit" && dirty && !confirm(t("recipe.discardConfirm"))) return;
    setMode("list");
    setActiveRecipeId(null);
    setRecipeName(t("recipe.untitledRecipe"));
    setItems([]);
    setInstructions([]);
    setServings(4);
    setImagePath(null);
    setDirty(false);
    setError("");
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
      const loaded: RecipeItem[] = gen.ingredients.map((gi) => ({
        ingredient: resolveIngredient(allIngredients, gi.fdc_id, gi.name),
        quantity_g: gi.quantity_g,
      }));
      setItems(loaded);
      setDirty(true);
      setMode("edit");
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
      const mt = mealType || null;
      if (activeRecipeId) {
        await updateRecipe(activeRecipeId, { name: recipeName, ingredients, instructions, servings, meal_type: mt });
      } else {
        const created = await createRecipe(recipeName, ingredients, instructions, servings, mt);
        setActiveRecipeId(created.id);
      }
      setDirty(false);
      void ensureIngredientImages(items.map((i) => i.ingredient.fdc_id));
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

  // -----------------------------------------------------------------
  // Cookbook chapters — categorise each recipe by dominant protein.
  // Scans the recipe name + every ingredient name; the first chapter
  // whose regex hits wins. The order here is the order on the page.
  // -----------------------------------------------------------------

  const CHAPTERS: { key: string; label: string; re: RegExp }[] = useMemo(() => [
    { key: "chicken",    label: t("recipe.chapters.chicken"),    re: /\b(chicken|poultry)\b/ },
    { key: "beef",       label: t("recipe.chapters.beef"),       re: /\b(beef|steak|brisket|chuck)\b/ },
    { key: "pork",       label: t("recipe.chapters.pork"),       re: /\b(pork|bacon|ham|sausage|chorizo|pancetta|lardon|prosciutto|frikadel)\b/ },
    { key: "lamb",       label: t("recipe.chapters.lamb"),       re: /\b(lamb|mutton)\b/ },
    { key: "fish",       label: t("recipe.chapters.fish"),       re: /\b(salmon|cod|tuna|halibut|trout|tilapia|sea bass|gravlax|mackerel|fish)\b/ },
    { key: "seafood",    label: t("recipe.chapters.seafood"),    re: /\b(shrimp|prawn|scallop|crab|lobster|squid|calamari|mussel|clam|oyster)\b/ },
    { key: "pasta",      label: t("recipe.chapters.pasta"),      re: /\b(pasta|spaghetti|linguine|fettuccine|penne|risotto|gnocchi|orzo|ravioli|lasagna|noodle)\b/ },
    { key: "vegetarian", label: t("recipe.chapters.vegetarian"), re: /(.*)/ },  // catch-all
  ], [t]);

  function chapterFor(r: Recipe): string {
    const haystack = (
      r.name + " " + r.ingredients.map((i) => i.ingredient_name ?? "").join(" ")
    ).toLowerCase();
    for (const c of CHAPTERS) {
      if (c.re.test(haystack)) return c.key;
    }
    return "vegetarian";
  }

  const groupedByChapter = useMemo(() => {
    const m: Record<string, Recipe[]> = {};
    for (const r of recipes) {
      const cat = chapterFor(r);
      (m[cat] ||= []).push(r);
    }
    for (const k of Object.keys(m)) {
      m[k].sort((a, b) => a.name.localeCompare(b.name));
    }
    return m;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recipes]);

  return (
    <div className="col gap-5">
      <ErrorBanner>{error}</ErrorBanner>

      {mode === "list" && (
        <div className="hero">
          <h1>{t("recipe.heroTitle")}</h1>
          <p>{t("recipe.heroIntro")}</p>
        </div>
      )}

      {/* Saved recipes — the browse list */}
      {mode === "list" && (
      <div className="col gap-2">
        <div className="row gap-2 items-baseline">
          <h3 className="muted small overline m-0 flex-1">
            {t("recipe.cookbookTitle")} {recipes.length > 0 && <span className="ml-1">· {recipes.length}</span>}
          </h3>
          <Button onClick={newRecipe} variant="primary" size="sm">
            <Plus size={14} /> {t("recipe.create")}
          </Button>
        </div>

        {recipes.length === 0 ? (
          <Card variant="soft" className="text-center">
            <p className="muted">{t("recipe.noSavedRecipes")}</p>
            <Button variant="primary" onClick={handleSeedStarters} disabled={seeding}>
              <Sparkles size={14} /> {seeding ? t("recipe.importing") : t("recipe.importStarters")}
            </Button>
            {seedMessage && <p className="small muted mt-2">{seedMessage}</p>}
          </Card>
        ) : (() => {
          const visibleList = activeChapter === "all"
            ? [...recipes].sort((a, b) => a.name.localeCompare(b.name))
            : (groupedByChapter[activeChapter] ?? []);
          return (
            <>
              {/* Cookbook tab strip */}
              <div className="cookbook-tabs" role="tablist">
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeChapter === "all"}
                  onClick={() => setActiveChapter("all")}
                  className={"cookbook-tab" + (activeChapter === "all" ? " cookbook-tab-active" : "")}
                >
                  <span className="cookbook-tab-label">{t("recipe.chapterAll")}</span>
                  <span className="cookbook-tab-count">{recipes.length}</span>
                </button>
                {CHAPTERS.map((c) => {
                  const count = groupedByChapter[c.key]?.length ?? 0;
                  if (!count) return null;
                  return (
                    <button
                      key={c.key}
                      type="button"
                      role="tab"
                      aria-selected={activeChapter === c.key}
                      onClick={() => setActiveChapter(c.key)}
                      className={"cookbook-tab" + (activeChapter === c.key ? " cookbook-tab-active" : "")}
                    >
                      <span className="cookbook-tab-label">{c.label}</span>
                      <span className="cookbook-tab-count">{count}</span>
                    </button>
                  );
                })}
              </div>

              {/* Cards */}
              <div className="cookbook-grid">
                {visibleList.map((r) => {
                  const toBuy = r.ingredients.length;
                  return (
                    <button
                      key={r.id}
                      type="button"
                      onClick={() => openRecipe(r)}
                      className={"cookbook-card" + (r.id === activeRecipeId ? " cookbook-card-active" : "")}
                    >
                      <div className="cookbook-card-img">
                        {r.image_path ? (
                          <img src={`/api/recipe-images/${r.image_path}`} alt="" draggable={false} />
                        ) : (
                          <div className="cookbook-card-placeholder">
                            <ChefHat size={32} />
                          </div>
                        )}
                        <IconButton
                          className="cookbook-card-remove"
                          onClick={(e) => { e.stopPropagation(); handleDelete(r.id); }}
                          aria-label={t("recipe.deleteRecipe")}
                        >
                          <X size={12} />
                        </IconButton>
                      </div>
                      <div className="cookbook-card-body">
                        <h4 className="cookbook-card-title">{r.name}</h4>
                        <div className="cookbook-card-meta">
                          {r.meal_type && (
                            <span className="cookbook-card-pill pill-match">{el.slot(r.meal_type)}</span>
                          )}
                          <span>{t("recipe.toBuyCount", { count: toBuy })}</span>
                          <span>·</span>
                          <span>{t("recipe.stepCount", { count: r.instructions.length })}</span>
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </>
          );
        })()}
      </div>
      )}

      {/* Read-only recipe view — opens when a card is clicked. Editing is one
          tap away via the Edit button; nothing is mutable here. */}
      {mode === "view" && (
      <>
      <div className="row items-center gap-2">
        <Button variant="ghost" size="sm" onClick={backToList}>
          <ArrowLeft size={14} />
          <span className="ml-1">{t("recipe.backToRecipes")}</span>
        </Button>
      </div>
      <Card>
        {imagePath && (
          <div className="recipe-hero">
            <img
              src={`/api/recipe-images/${imagePath}?v=${imageBust}`}
              alt={recipeName}
              className="recipe-hero-img"
            />
          </div>
        )}
        <div className="row gap-3 wrap items-center">
          <h2 className="m-0 flex-1">{recipeName}</h2>
          {mealType && <Pill>{el.slot(mealType)}</Pill>}
          <div className="row gap-2 items-center">
            <IconButton
              onClick={() => setViewServings((v) => Math.max(1, v - 1))}
              title={t("cook.fewerServings")}
              aria-label={t("cook.fewerServings")}
            >
              <Minus size={14} />
            </IconButton>
            <span className="small fw-600">{t("recipe.servingsCount", { count: viewServings })}</span>
            <IconButton
              onClick={() => setViewServings((v) => Math.min(99, v + 1))}
              title={t("cook.moreServings")}
              aria-label={t("cook.moreServings")}
            >
              <Plus size={14} />
            </IconButton>
          </div>
          <Button variant="ghost" size="sm" onClick={() => setMode("edit")}>
            <Pencil size={14} /><span className="ml-1">{t("common.edit")}</span>
          </Button>
          <Button
            variant="accent"
            onClick={() => setCookOpen(true)}
            disabled={items.length === 0 && instructions.length === 0}
            title={t("recipe.startCookingTitle")}
          >
            <ChefHat size={14} /><span className="ml-1">{t("recipe.startCooking")}</span>
          </Button>
        </div>

        <Divider />

        <div className="row gap-5 wrap items-start">
          <div className="flex-1 min-w-320">
            <h3>{t("recipe.ingredients")} <span className="muted small">({items.length})</span></h3>
            {items.length === 0 && <Empty>{t("recipe.pickIngredients")}</Empty>}
            <div className="col-2">
              {items.map((item) => (
                <div key={item.ingredient.fdc_id} className="row gap-2 items-center inset">
                  <IngredientThumb fdcId={item.ingredient.fdc_id} group={item.ingredient.food_group} />
                  <span className="flex-1 fw-500">{el.ingredient(item.ingredient.fdc_id, item.ingredient.name)}</span>
                  <span className="small muted">
                    {Math.max(1, Math.round(item.quantity_g * viewServings / Math.max(1, servings)))} {t("recipe.grams")}
                  </span>
                </div>
              ))}
            </div>
          </div>
          <div className="flex-1 min-w-320">
            <h3>{t("recipe.instructions")}</h3>
            {instructions.length === 0 && <Empty>{t("recipe.noStepsYet")}</Empty>}
            <ol className="recipe-steps">
              {instructions.map((step, i) => <li key={i}>{step}</li>)}
            </ol>
          </div>
        </div>
      </Card>
      </>
      )}

      {/* Editor / create view: name, ingredients, instructions, save. Opens on
          "+ Create", a recipe-card click, or a successful AI generate. The AI
          prompt lives here (only while creating a new recipe), so the browse
          view stays a clean list. backToList() returns to the list. */}
      {mode === "edit" && (
      <>
      <div className="row items-center gap-2">
        <Button variant="ghost" size="sm" onClick={backToList}>
          <ArrowLeft size={14} />
          <span className="ml-1">{t("recipe.backToRecipes")}</span>
        </Button>
      </div>
      {!activeRecipeId && (
        <Card variant="warm">
          <div className="row gap-3">
            <Sparkles size={22} />
            <div className="flex-1 col-2">
              <h4 className="m-0">{t("recipe.generateTitle")}</h4>
              <span className="small muted">{t("recipe.generateHint")}</span>
            </div>
          </div>
          <div className="row gap-2 mt-3">
            <Input
              placeholder={t("recipe.generatePlaceholder")}
              value={genPrompt}
              onChange={(e) => setGenPrompt(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !generating && handleGenerate()}
              disabled={generating}
            />
            <Button onClick={handleGenerate} disabled={generating || !genPrompt.trim()} variant="accent">
              {generating ? t("recipe.thinking") : t("common.generate")}
            </Button>
          </div>
        </Card>
      )}
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
                <span className="tiny muted">{t("recipe.generatingImage")}</span>
              </div>
            )}
            <Button
              onClick={handleRegenerateImage}
              disabled={regenerating}
              size="xs"
              className="recipe-hero-regen"
              title={t("recipe.regenerateImageTitle")}
            >
              {regenerating ? "…" : <><RefreshCw size={12} /> {t("recipe.regenerateImage")}</>}
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
            {t("recipe.servings")}
            <Input
              type="number"
              min={1}
              numeric
              value={servings}
              onChange={(e) => { setServings(Math.max(1, Number(e.target.value) || 1)); markDirty(); }}
            />
          </Field>
          <Field>
            {t("recipe.mealType")}
            <Select
              value={mealType}
              onChange={(v) => { setMealType(v as typeof mealType); markDirty(); }}
              options={[
                { value: "", label: t("recipe.mealTypeAny") },
                { value: "breakfast", label: el.slot("breakfast") },
                { value: "lunch", label: el.slot("lunch") },
                { value: "dinner", label: el.slot("dinner") },
              ]}
            />
          </Field>
          <Button onClick={saveRecipe} disabled={saving || (!dirty && activeRecipeId !== null)} variant="primary">
            {saving ? t("common.saving") : activeRecipeId ? t("common.save") : t("recipe.create")}
          </Button>
          <Button
            onClick={() => setCookOpen(true)}
            disabled={items.length === 0 && instructions.length === 0}
            variant="accent"
            title={t("recipe.startCookingTitle")}
          >
            <ChefHat size={14} />
            <span className="ml-1">{t("recipe.startCooking")}</span>
          </Button>
        </div>

        <Divider />

        <div className="row gap-5 wrap items-start">
          {/* Left: pantry picker */}
          <div className="flex-1 min-w-320">
            <div className="row between mb-2">
              <h3 className="m-0">{t("recipe.pantry")}</h3>
              <Button onClick={() => setUsdaOpen(!usdaOpen)} variant="ghost" size="sm">
                {usdaOpen ? t("recipe.closeUsda") : <><Plus size={14} /> {t("recipe.findMore")}</>}
              </Button>
            </div>

            {usdaOpen && (
              <Card variant="soft" className="mb-3">
                <div className="row gap-2 mb-2">
                  <Input
                    placeholder={t("recipe.usdaPlaceholder")}
                    value={usdaQuery}
                    onChange={(e) => setUsdaQuery(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleUsdaSearch()}
                  />
                  <Button onClick={handleUsdaSearch} disabled={usdaLoading} size="sm">
                    {usdaLoading ? "..." : t("common.search")}
                  </Button>
                </div>
                <div className="scroll-y maxh-360">
                  {usdaResults.map((r) => (
                    <ListRow key={r.fdc_id}>
                      <div className="flex-1">
                        <div>{el.ingredient(r.fdc_id, r.name)}</div>
                        <div className="tiny muted">→ {r.mapped_category}{r.food_group ? ` · ${r.food_group}` : ""}</div>
                      </div>
                      <Button onClick={() => promoteToPantry(r)} disabled={r.in_pantry} size="xs">
                        {r.in_pantry ? <><Check size={12} /> {t("recipe.inPantry")}</> : <><Plus size={12} /> {t("common.add")}</>}
                      </Button>
                    </ListRow>
                  ))}
                  {usdaResults.length === 0 && usdaQuery && !usdaLoading && (
                    <p className="muted small mt-2">{t("recipe.usdaNoResults")}</p>
                  )}
                </div>
              </Card>
            )}

            <div className="row gap-2 mb-3">
              <Select
                className="w-auto"
                value={selectedCat}
                onChange={setSelectedCat}
                options={[
                  { value: "", label: t("recipe.allCategories") },
                  ...categories.map((c) => ({ value: c, label: c })),
                ]}
              />
              <Input
                className="flex-1"
                placeholder={t("recipe.filterByName")}
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
                      <div className="fw-500">{el.ingredient(ing.fdc_id, ing.name)}</div>
                      <div className="tiny muted">{t("recipe.perHundredGram", { kcal: ing.energy_kcal_100g ?? "?", protein: ing.proteins_100g ?? "?" })}</div>
                    </div>
                    <Button onClick={() => addItem(ing)} disabled={added} size="xs">
                      {added ? t("recipe.added") : <Plus size={14} />}
                    </Button>
                  </ListRow>
                );
              })}
              {filtered.length === 0 && <Empty>{t("recipe.noIngredientsMatch")}</Empty>}
            </List>
          </div>

          {/* Right: current recipe — the full ingredient list */}
          <div className="flex-1 min-w-320">
            <h3>{t("recipe.ingredients")} <span className="muted small">({items.length})</span></h3>
            {items.length === 0 && (
              <Empty>{t("recipe.pickIngredients")}</Empty>
            )}
            <div className="col-2">
              {items.map((item) => (
                <div key={item.ingredient.fdc_id} className="row gap-2 inset">
                  <div className="flex-1 fw-500">{el.ingredient(item.ingredient.fdc_id, item.ingredient.name)}</div>
                  <Input
                    type="number" numeric
                    value={item.quantity_g}
                    onChange={(e) => updateQuantity(item.ingredient.fdc_id, Number(e.target.value) || 0)}
                    min={0}
                  />
                  <span className="small muted">{t("recipe.grams")}</span>
                  <IconButton onClick={() => removeItem(item.ingredient.fdc_id)} aria-label={t("common.remove")}>
                    <X size={14} />
                  </IconButton>
                </div>
              ))}
            </div>

            {nutrition && (
              <Card variant="accent" className="mt-4">
                <h4>{t("recipe.nutrition")}</h4>
                <table className="table">
                  <tbody>
                    {[
                      [t("recipe.nutritionWeight"), nutrition.total_weight_g, "g"],
                      [t("recipe.nutritionEnergy"), nutrition.total_energy_kcal, "kcal"],
                      [t("recipe.nutritionProtein"), nutrition.total_proteins_g, "g"],
                      [t("recipe.nutritionCarbs"), nutrition.total_carbohydrates_g, "g"],
                      [t("recipe.nutritionSugars"), nutrition.total_sugars_g, "g"],
                      [t("recipe.nutritionFat"), nutrition.total_fat_g, "g"],
                      [t("recipe.nutritionSaturatedFat"), nutrition.total_saturated_fat_g, "g"],
                      [t("recipe.nutritionFiber"), nutrition.total_fiber_g, "g"],
                      [t("recipe.nutritionSalt"), nutrition.total_salt_g, "g"],
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
                    {t("recipe.nutritionMissing")}
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
            <h3 className="m-0">{t("recipe.instructions")}</h3>
            <Button
              onClick={() => { setInstructions((prev) => [...prev, ""]); markDirty(); }}
              size="sm"
            >
              <Plus size={14} /> {t("recipe.step")}
            </Button>
          </div>
          {instructions.length === 0 && (
            <Empty>{t("recipe.noStepsYet")}</Empty>
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
                  aria-label={t("recipe.removeStep")}
                >
                  <X size={14} />
                </IconButton>
              </li>
            ))}
          </ol>
        </div>
      </Card>
      </>
      )}

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

/** Small category icon shown beside each ingredient in the read-only view.
    USDA gives no per-ingredient photos, so we map the food group to a lucide
    food icon (raw value falls through to a generic utensils icon). */
function IngredientIcon({ group }: { group: string | null }) {
  const g = (group ?? "").toLowerCase();
  const has = (...keys: string[]) => keys.some((k) => g.includes(k));
  let Icon = UtensilsCrossed;
  if (has("dairy", "egg", "milk", "cheese", "yogurt", "cream")) Icon = Milk;
  else if (has("poultry", "chicken", "turkey")) Icon = Drumstick;
  else if (has("beef", "pork", "lamb", "veal", "sausage", "meat")) Icon = Beef;
  else if (has("fish", "shellfish", "seafood", "finfish")) Icon = Fish;
  else if (has("veget")) Icon = Carrot;
  else if (has("fruit")) Icon = Apple;
  else if (has("cereal", "grain", "pasta", "bread", "baked", "rice", "flour")) Icon = Wheat;
  else if (has("legume", "nut", "bean", "seed")) Icon = Nut;
  else if (has("fat", "oil")) Icon = Droplet;
  else if (has("soup", "sauce", "gravy")) Icon = Soup;
  return <Icon size={18} className="ing-icon" />;
}

/** Generated ingredient thumbnail (cached by fdc_id); falls back to the
    category icon until/unless an image exists. */
function IngredientThumb({ fdcId, group }: { fdcId: number; group: string | null }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return <span className="ing-thumb ing-thumb-fallback"><IngredientIcon group={group} /></span>;
  }
  return (
    <img
      src={`/api/ingredient-images/${fdcId}.png`}
      alt=""
      className="ing-thumb"
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}
