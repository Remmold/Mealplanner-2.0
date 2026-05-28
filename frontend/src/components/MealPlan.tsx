import { useEffect, useMemo, useState } from "react";
import { Plus, ShoppingCart, Sparkles, X } from "lucide-react";
import {
  fetchMealPlans,
  createMealPlan,
  updateMealPlan,
  deleteMealPlan,
  mealPlanShoppingList,
  fetchRecipes,
  generateMealPlan,
  onDataChanged,
  type MealPlan,
  type MealPlanEntry,
  type Recipe,
  type ShoppingList,
} from "../api";
import { fetchProfile, type ProfileSummary } from "../lib/auth-api";
import { Button, Card, Chip, Divider, Empty, ErrorBanner, Field, IconButton, Input, Modal, Pill, Textarea } from "./ui";

const DAYS = 7;
const SLOTS = ["breakfast", "lunch", "dinner"] as const;
type Slot = typeof SLOTS[number];

function isoDate(d: Date): string { return d.toISOString().slice(0, 10); }
function addDays(iso: string, n: number): string {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + n);
  return isoDate(d);
}
function formatDay(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

export default function MealPlan() {
  const [plans, setPlans] = useState<MealPlan[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [planName, setPlanName] = useState("Week of " + isoDate(new Date()));
  const [startDate, setStartDate] = useState(isoDate(new Date()));
  const [entries, setEntries] = useState<MealPlanEntry[]>([]);
  const [dirty, setDirty] = useState(false);

  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [pickerCell, setPickerCell] = useState<{ date: string; slot: Slot } | null>(null);

  const [shopping, setShopping] = useState<ShoppingList | null>(null);
  const [error, setError] = useState("");

  // AI weekly generator — wizard-style 3-step flow
  const [genOpen, setGenOpen] = useState(false);
  const [genStep, setGenStep] = useState<0 | 1 | 2>(0);
  const [genPrompt, setGenPrompt] = useState("");
  const [genStart, setGenStart] = useState(isoDate(new Date()));
  const [genDays, setGenDays] = useState(7);
  const [genServings, setGenServings] = useState(4);
  // Per-slot batch-cook tuning (portions / distinct caps) is intentionally
  // hidden from the UI — the planner agent infers it from keywords in the
  // brief ("batch-cook", "matlåda", "meal prep") and applies defaults
  // otherwise. Keeps the wizard focused.
  const [enabledSlots, setEnabledSlots] = useState<Set<Slot>>(new Set(["dinner"]));
  const [generating, setGenerating] = useState(false);
  const [genElapsed, setGenElapsed] = useState(0);

  function openGenerator() {
    setGenStep(0);
    setError("");
    setGenOpen(true);
  }

  function closeGenerator() {
    if (generating) return;
    setGenOpen(false);
    // Don't reset other state — if the user reopens, their last settings
    // are still there. genStep resets on next openGenerator().
  }

  // Profile context the generator should respect. Loaded once on mount;
  // refreshed when the chat agent edits the profile.
  const [profile, setProfile] = useState<ProfileSummary | null>(null);

  useEffect(() => {
    reloadPlans();
    fetchRecipes().then(setRecipes).catch((e) => setError(String(e)));
    fetchProfile().then((p) => {
      setProfile(p);
      // Pre-fill servings from family_size so the user doesn't have to.
      if (p.family_size && p.family_size > 0) setGenServings(p.family_size);
    }).catch(() => { /* sparse profile is fine */ });
  }, []);

  // Refresh when the chat agent mutates anything
  useEffect(() => {
    return onDataChanged((kind) => {
      if (kind === "*" || kind === "meal_plans") reloadPlans();
      if (kind === "*" || kind === "recipes") fetchRecipes().then(setRecipes).catch(() => {});
      if (kind === "*") fetchProfile().then(setProfile).catch(() => {});
    });
  }, []);

  async function reloadPlans() {
    try { setPlans(await fetchMealPlans()); } catch (e) { setError(String(e)); }
  }

  function newPlan() {
    setActiveId(null);
    const today = isoDate(new Date());
    setPlanName("Week of " + today);
    setStartDate(today);
    setEntries([]);
    setShopping(null);
    setDirty(false);
  }

  function loadPlan(p: MealPlan) {
    setActiveId(p.id);
    setPlanName(p.name);
    setStartDate(p.start_date);
    setEntries(p.entries);
    setShopping(null);
    setDirty(false);
  }

  const dates = useMemo(
    () => Array.from({ length: DAYS }, (_, i) => addDays(startDate, i)),
    [startDate]
  );

  function entriesAt(date: string, slot: Slot): MealPlanEntry[] {
    return entries.filter((e) => e.plan_date === date && e.slot === slot);
  }

  function addRecipeToCell(recipe: Recipe) {
    if (!pickerCell) return;
    const newEntry: MealPlanEntry = {
      id: "new-" + Math.random().toString(36).slice(2),
      recipe_id: recipe.id,
      recipe_name: recipe.name,
      plan_date: pickerCell.date,
      slot: pickerCell.slot,
      portions: recipe.servings,
    };
    setEntries((prev) => [...prev, newEntry]);
    setPickerCell(null);
    setDirty(true);
  }

  function removeEntry(id: string) {
    setEntries((prev) => prev.filter((e) => e.id !== id));
    setDirty(true);
  }
  function updateEntryPortions(id: string, portions: number) {
    setEntries((prev) => prev.map((e) => (e.id === id ? { ...e, portions: Math.max(1, portions) } : e)));
    setDirty(true);
  }

  async function savePlan() {
    try {
      const payload = {
        name: planName, start_date: startDate,
        entries: entries.map((e) => ({
          recipe_id: e.recipe_id, plan_date: e.plan_date, slot: e.slot, portions: e.portions,
        })),
      };
      let saved: MealPlan;
      if (activeId) saved = await updateMealPlan(activeId, payload);
      else { saved = await createMealPlan(payload.name, payload.start_date, payload.entries); setActiveId(saved.id); }
      setEntries(saved.entries); setDirty(false); await reloadPlans();
    } catch (e) { setError(String(e)); }
  }

  async function removePlan(id: string) {
    try { await deleteMealPlan(id); if (activeId === id) newPlan(); await reloadPlans(); }
    catch (e) { setError(String(e)); }
  }

  async function runWeeklyGenerator() {
    // Per-slot portions/distinct hidden from UI; planner infers from brief.
    const slot_configs = Array.from(enabledSlots).map((s) => ({
      slot: s,
      portions: 1,
      distinct_meals: null,
    }));
    if (slot_configs.length === 0) { setError("Pick at least one meal slot"); return; }
    setGenerating(true); setError(""); setGenElapsed(0);
    const t0 = Date.now();
    const timer = setInterval(() => setGenElapsed(Math.round((Date.now() - t0) / 1000)), 1000);
    try {
      // Empty brief is fine — the planner falls back to the household profile.
      // Send a generic anchor so the LLM has something to riff off.
      const promptText = genPrompt.trim() || "A balanced week using the household's typical preferences.";
      const plan = await generateMealPlan({
        prompt: promptText,
        start_date: genStart,
        days: genDays,
        servings: genServings,
        slot_configs,
      });
      await reloadPlans();
      // Load the generated plan into the editor
      setActiveId(plan.id);
      setPlanName(plan.name);
      setStartDate(plan.start_date);
      setEntries(plan.entries);
      setShopping(null);
      setDirty(false);
      // Refresh recipes since new ones were probably created
      fetchRecipes().then(setRecipes).catch(() => {});
      setGenOpen(false);
      setGenPrompt("");
    } catch (e) {
      setError(String(e));
    } finally {
      clearInterval(timer);
      setGenerating(false);
    }
  }

  async function generateShopping() {
    if (!activeId) { setError("Save the plan before generating a shopping list."); return; }
    try { setShopping(await mealPlanShoppingList(activeId)); }
    catch (e) { setError(String(e)); }
  }

  return (
    <div className="col gap-5">
      <div className="hero">
        <h1>Plan the week</h1>
        <p>Drop saved recipes into the days you want to cook them. Generate a single, store-ordered shopping list for the whole week.</p>
      </div>

      <ErrorBanner>{error}</ErrorBanner>

      {/* Plans bar */}
      <div className="col gap-2">
        <h3 className="muted small overline m-0">Your plans</h3>
        <div className="row wrap gap-2">
          <Button onClick={newPlan} variant="primary" size="sm"><Plus size={14} /> New plan</Button>
          <Button onClick={openGenerator} variant="accent" size="sm"><Sparkles size={14} /> Generate week with AI</Button>
          {plans.map((p) => (
            <Chip
              key={p.id}
              active={p.id === activeId}
              onClick={() => loadPlan(p)}
              onRemove={() => removePlan(p.id)}
            >
              {p.name}
            </Chip>
          ))}
          {plans.length === 0 && <span className="muted small">No plans yet.</span>}
        </div>
      </div>

      {/* Editor card */}
      <Card>
        <div className="row gap-3 wrap">
          <Input
            variant="title"
            className="flex-1 min-w-240"
            value={planName}
            onChange={(e) => { setPlanName(e.target.value); setDirty(true); }}
          />
          <Field>
            Start date
            <Input
              type="date"
              className="w-auto"
              value={startDate}
              onChange={(e) => { setStartDate(e.target.value); setDirty(true); }}
            />
          </Field>
          <Button onClick={savePlan} disabled={!dirty && activeId !== null} variant="primary">
            {activeId ? "Save" : "Create"}
          </Button>
          <Button onClick={generateShopping} disabled={!activeId || dirty} variant="accent">
            <ShoppingCart size={16} /> Shopping list
          </Button>
        </div>

        <Divider />

        <div className="scroll-x">
          <table className="week-grid">
            <thead>
              <tr>
                <th className="slot-th"></th>
                {dates.map((d) => (
                  <th key={d}>{formatDay(d)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {SLOTS.map((slot) => (
                <tr key={slot}>
                  <td className="slot-th">{slot}</td>
                  {dates.map((date) => {
                    const cellEntries = entriesAt(date, slot);
                    return (
                      <td key={date + slot}>
                        {cellEntries.map((e) => (
                          <div key={e.id} className="cell-entry">
                            <div className="cell-entry-name">{e.recipe_name}</div>
                            <div className="row gap-2">
                              <Input
                                type="number" min={1} value={e.portions}
                                onChange={(ev) => updateEntryPortions(e.id, Number(ev.target.value) || 1)}
                                className="input-mini"
                              />
                              <span className="tiny muted">portions</span>
                              <IconButton onClick={() => removeEntry(e.id)} className="icon-btn-sm ml-auto" aria-label="Remove">
                                <X size={12} />
                              </IconButton>
                            </div>
                          </div>
                        ))}
                        <button onClick={() => setPickerCell({ date, slot })} className="cell-add" aria-label="Add recipe">
                          <Plus size={14} />
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* AI weekly plan generator — guided 3-step wizard so no single screen
          drowns the user in fields. Per-slot batch tuning is intentionally
          hidden (the planner reads "batch-cook"/"matlåda" from the brief). */}
      <Modal open={genOpen} onClose={closeGenerator} className="modal-lg">
        <h3 className="row gap-2"><Sparkles size={18} /> Plan this week</h3>

        <div className="tour-dots mt-2" aria-hidden>
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className={"tour-dot" + (i === genStep ? " tour-dot-active" : "")}
            />
          ))}
        </div>

        {genStep === 0 && (
          <div className="col-2 mt-3">
            <p className="muted m-0">First, the basics. Defaults pulled from your profile.</p>
            <Field>
              Cooking for how many?
              <Input
                type="number" min={1} numeric
                value={genServings}
                onChange={(e) => setGenServings(Math.max(1, Number(e.target.value) || 4))}
                disabled={generating}
                autoFocus
              />
            </Field>
            <div className="row gap-3 wrap">
              <Field>
                Start date
                <Input
                  type="date"
                  value={genStart}
                  onChange={(e) => setGenStart(e.target.value)}
                  disabled={generating}
                />
              </Field>
              <Field>
                How many days?
                <Input
                  type="number" min={1} max={14} numeric
                  value={genDays}
                  onChange={(e) => setGenDays(Math.max(1, Math.min(14, Number(e.target.value) || 7)))}
                  disabled={generating}
                />
              </Field>
            </div>
          </div>
        )}

        {genStep === 1 && (
          <div className="col-2 mt-3">
            <p className="muted m-0">Which meals should Hearth plan? Most people just do dinner.</p>
            <div className="col-2">
              {(["breakfast", "lunch", "dinner"] as Slot[]).map((s) => {
                const enabled = enabledSlots.has(s);
                return (
                  <label key={s} className="meal-toggle">
                    <input
                      type="checkbox"
                      checked={enabled}
                      onChange={() => setEnabledSlots((prev) => {
                        const next = new Set(prev);
                        if (next.has(s)) next.delete(s); else next.add(s);
                        return next;
                      })}
                      disabled={generating}
                    />
                    <span className="capitalize">{s}</span>
                  </label>
                );
              })}
            </div>
          </div>
        )}

        {genStep === 2 && (
          <div className="col-2 mt-3">
            <ProfileContextCard profile={profile} />
            <Field className="field-col">
              <span className="small muted">Anything special this week? <em>(optional)</em></span>
              <Textarea
                placeholder="e.g. 'batch-cook 3 dinners', 'meatless Monday', 'lighter than last week'"
                value={genPrompt}
                onChange={(e) => setGenPrompt(e.target.value)}
                rows={2}
                disabled={generating}
              />
            </Field>
          </div>
        )}

        <div className="row gap-2 mt-4">
          {genStep > 0 ? (
            <Button variant="ghost" onClick={() => setGenStep((s) => (s - 1) as 0 | 1 | 2)} disabled={generating}>
              Back
            </Button>
          ) : (
            <Button variant="ghost" onClick={closeGenerator} disabled={generating}>
              Cancel
            </Button>
          )}
          {genStep < 2 ? (
            <Button
              variant="primary"
              onClick={() => setGenStep((s) => (s + 1) as 0 | 1 | 2)}
              disabled={generating}
              className="flex-1"
            >
              Continue
            </Button>
          ) : (
            <Button
              variant="accent"
              onClick={runWeeklyGenerator}
              disabled={generating}
              className="flex-1"
            >
              {generating ? "Drafting your week..." : "Generate this week's plan"}
            </Button>
          )}
        </div>

        {generating && (
          <Card variant="soft" className="mt-3">
            <div className="row gap-2">
              <div className="chat-typing"><span></span><span></span><span></span></div>
              <div className="flex-1">
                <div className="fw-500">Drafting your week…</div>
                <div className="tiny muted">
                  {genElapsed}s elapsed · planner runs first, then recipes generate in parallel. Usually 30–90s total.
                </div>
              </div>
            </div>
          </Card>
        )}
      </Modal>

      {/* Recipe picker modal */}
      <Modal open={!!pickerCell} onClose={() => setPickerCell(null)}>
        {pickerCell && (
          <>
            <h3>Pick a recipe</h3>
            <p className="small muted">{formatDay(pickerCell.date)} · <span className="capitalize">{pickerCell.slot}</span></p>
            {recipes.length === 0 && <Empty>No saved recipes.</Empty>}
            <div className="col-2 mt-3">
              {recipes.map((r) => (
                <div key={r.id} onClick={() => addRecipeToCell(r)} className="recipe-card horizontal">
                  {r.image_path ? (
                    <img src={`/api/recipe-images/${r.image_path}`} alt="" className="recipe-thumb" />
                  ) : (
                    <div className="recipe-thumb" />
                  )}
                  <div className="flex-1">
                    <div className="fw-600">{r.name}</div>
                    <div className="tiny muted">{r.servings} servings · {r.ingredients.length} ingredients</div>
                  </div>
                </div>
              ))}
            </div>
            <Button onClick={() => setPickerCell(null)} variant="ghost" className="mt-3">Cancel</Button>
          </>
        )}
      </Modal>

      {/* Generated shopping list */}
      {shopping && (
        <Card>
          <h3>Shopping list</h3>
          {shopping.categories.length === 0 && <Empty>No items.</Empty>}
          {shopping.categories.map((cat) => (
            <div key={cat.category} className="mb-3">
              <div className="shop-cat-header">
                <span>{cat.category}</span>
                <span className="shop-cat-count">{cat.items.length} items</span>
              </div>
              {cat.items.map((item) => (
                <div key={item.fdc_id} className="shop-row">
                  <span className="flex-1">{item.name}</span>
                  <span className="shop-qty">{item.display_quantity} {item.display_unit}</span>
                  {item.display_unit !== "g" && (
                    <span className="tiny muted">({Math.round(item.quantity_g)} g)</span>
                  )}
                </div>
              ))}
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}


/**
 * The "Hearth knows X about your household" card shown above the generate
 * prompt. Renders profile chips when there's something to show; nudges the
 * user to chat with the assistant when the profile is sparse.
 */
function ProfileContextCard({ profile }: { profile: ProfileSummary | null }) {
  if (!profile) {
    return (
      <Card variant="soft" className="mt-2">
        <p className="small muted m-0">
          Loading your household preferences…
        </p>
      </Card>
    );
  }

  const chips: string[] = [];
  if (profile.family_size && profile.family_size > 0) {
    chips.push(`cooking for ${profile.family_size}`);
  }
  profile.dietary.forEach((d) => chips.push(d));
  if (profile.allergies.length > 0) {
    chips.push(`no ${profile.allergies.join(", ")}`);
  }
  if (profile.typical_cook_time_min) {
    chips.push(`~${profile.typical_cook_time_min} min weeknights`);
  }
  profile.cuisines.slice(0, 4).forEach((c) => chips.push(c));
  if (profile.batch_cook_preference && profile.batch_cook_preference !== "none") {
    chips.push(`batch-cook ${profile.batch_cook_preference}`);
  }

  if (chips.length === 0) {
    return (
      <Card variant="soft" className="mt-2">
        <p className="small m-0">
          Your profile is empty — Hearth will guess from a typical household.
        </p>
        <p className="tiny muted m-0 mt-1">
          Open the chat and tell it about your preferences (family size, diet,
          allergies, favourite cuisines). It will remember for next time.
        </p>
      </Card>
    );
  }

  return (
    <Card variant="soft" className="mt-2">
      <p className="tiny muted m-0">Hearth will use what we've learned so far:</p>
      <div className="row wrap gap-2 mt-2">
        {chips.map((c, i) => (
          <Pill key={i}>{c}</Pill>
        ))}
      </div>
      <p className="tiny muted m-0 mt-2">
        Wrong or missing? Open the chat and tell it — the assistant remembers.
      </p>
    </Card>
  );
}
