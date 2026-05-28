import { useEffect, useMemo, useState } from "react";
import { Check, Plus, Save, ShoppingCart, Sparkles, X } from "lucide-react";
import type { ReactNode } from "react";
import {
  fetchMealPlans,
  createMealPlan,
  updateMealPlan,
  deleteMealPlan,
  mealPlanShoppingList,
  fetchRecipes,
  generateMealPlan,
  onDataChanged,
  type GenerateEvent,
  type MealPlan,
  type MealPlanEntry,
  type Recipe,
  type ShoppingList,
} from "../api";
import { fetchProfile, type ProfileSummary } from "../lib/auth-api";
import { Button, Card, Chip, Divider, Empty, ErrorBanner, Field, IconButton, Input, Modal, Pill, Textarea } from "./ui";
import DateRangePicker from "./DateRangePicker";

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
  const [genEnd, setGenEnd] = useState(addDays(isoDate(new Date()), 6)); // 7 days inclusive
  const [genServings, setGenServings] = useState(4);
  // Per-slot batch-cook tuning (portions / distinct caps) is intentionally
  // hidden from the UI — the planner agent infers it from keywords in the
  // brief ("batch-cook", "matlåda", "meal prep") and applies defaults
  // otherwise. Keeps the wizard focused.
  const [enabledSlots, setEnabledSlots] = useState<Set<Slot>>(new Set(["dinner"]));
  const [generating, setGenerating] = useState(false);
  const [genElapsed, setGenElapsed] = useState(0);

  // Live progress feed from the streaming /meal-plans/generate endpoint.
  // One row per event, in order of arrival.
  interface FeedItem {
    id: string;
    status: "pending" | "done" | "failed";
    icon: ReactNode;
    text: string;
  }
  const [feed, setFeed] = useState<FeedItem[]>([]);

  // Inclusive day count: start = end means 1 day. Clamps any garbage input.
  const genDays = useMemo(() => {
    const ms = new Date(genEnd + "T00:00:00").getTime()
             - new Date(genStart + "T00:00:00").getTime();
    if (Number.isNaN(ms) || ms < 0) return 0;
    return Math.floor(ms / 86_400_000) + 1;
  }, [genStart, genEnd]);

  const genRangeError = genDays === 0
    ? "End date can't be before the start."
    : genDays > 14
    ? "Plans can be at most 14 days. Pick a closer end date."
    : null;

  function onStartChange(newStart: string) {
    setGenStart(newStart);
    // If the new start is after the current end, push end out to start + 6
    // so the user doesn't see a transient "invalid" state.
    if (new Date(newStart + "T00:00:00") > new Date(genEnd + "T00:00:00")) {
      setGenEnd(addDays(newStart, 6));
    }
  }

  function openGenerator() {
    setGenStep(0);
    setError("");
    setGenOpen(true);
  }

  function closeGenerator() {
    if (generating) return;
    setGenOpen(false);
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
    if (genRangeError) { setError(genRangeError); return; }
    setGenerating(true); setError(""); setGenElapsed(0);
    setFeed([]);
    const t0 = Date.now();
    const timer = setInterval(() => setGenElapsed(Math.round((Date.now() - t0) / 1000)), 1000);
    try {
      const promptText = genPrompt.trim() || "A balanced week using the household's typical preferences.";
      const plan = await generateMealPlan(
        {
          prompt: promptText,
          start_date: genStart,
          days: genDays,
          servings: genServings,
          slot_configs,
        },
        (event) => {
          const item = buildFeedItem(event);
          if (item) setFeed((prev) => [...prev, item]);
        },
      );
      // Push selected end date back so reopening shows the same window.
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

      {/* AI weekly plan generator — full-screen wizard takeover. Same warm
          shell as sign-in / welcome tour for visual continuity, instead of
          a generic centered modal. Three steps: basics, meals, brief. */}
      {genOpen && (
        <div className="plan-shell" role="dialog" aria-modal>
          <div className="brand auth-brand plan-shell-brand">
            <span className="brand-mark">Plan this week</span>
            <span className="brand-tag">Hearth drafts a plan and a shopping list</span>
          </div>

          <Card className="plan-shell-card">
            <div className="tour-dots" aria-hidden>
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className={"tour-dot" + (i === genStep ? " tour-dot-active" : "")}
                />
              ))}
            </div>

            {genStep === 0 && (
              <div className="col-2">
                <h2 className="m-0">The basics</h2>
                <p className="muted m-0">
                  Pick the dates and the table size. Defaults pulled from your profile.
                </p>

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

                <DateRangePicker
                  start={genStart}
                  end={genEnd}
                  onChange={(s, e) => { setGenStart(s); setGenEnd(e); }}
                  maxDays={14}
                />

                <p className="small muted m-0 text-center">
                  {formatDay(genStart)} → {formatDay(genEnd)} · {genDays} {genDays === 1 ? "day" : "days"}
                </p>
              </div>
            )}

            {genStep === 1 && (
              <div className="col-2">
                <h2 className="m-0">Which meals?</h2>
                <p className="muted m-0">
                  Most people just plan dinner. Pick whichever you want covered.
                </p>
                <div className="col-2 mt-2">
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
              <div className="col-2">
                <h2 className="m-0">Anything special this week?</h2>
                <p className="muted m-0">
                  Hearth respects your profile every time — only mention what
                  changes <em>this</em> week.
                </p>

                <ProfileContextCard profile={profile} />

                <Field className="field-col">
                  <Textarea
                    placeholder="e.g. 'batch-cook 3 dinners', 'meatless Monday', 'lighter than last week' — or leave blank."
                    value={genPrompt}
                    onChange={(e) => setGenPrompt(e.target.value)}
                    rows={3}
                    disabled={generating}
                  />
                </Field>
              </div>
            )}

            <div className="row gap-2 mt-4">
              {genStep > 0 ? (
                <Button
                  variant="ghost"
                  onClick={() => setGenStep((s) => (s - 1) as 0 | 1 | 2)}
                  disabled={generating}
                >
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
                  disabled={generating || (genStep === 0 && genRangeError !== null)}
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
              <Card variant="soft" className="mt-3 gen-feed">
                <div className="gen-feed-header">
                  <div className="chat-typing"><span></span><span></span><span></span></div>
                  <div className="flex-1">
                    <div className="fw-500">Drafting your week</div>
                    <div className="tiny muted">{genElapsed}s elapsed</div>
                  </div>
                </div>
                {feed.length > 0 && (
                  <ul className="gen-feed-list">
                    {feed.map((item) => (
                      <li
                        key={item.id}
                        className={`gen-feed-item gen-feed-${item.status}`}
                      >
                        <span className="gen-feed-icon">{item.icon}</span>
                        <span className="gen-feed-text">{item.text}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            )}
          </Card>
        </div>
      )}

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
 * Map a single streaming event onto a feed item the user sees in the live
 * progress card. Returns null for events we want to silently ignore.
 */
function buildFeedItem(event: GenerateEvent): {
  id: string;
  status: "pending" | "done" | "failed";
  icon: ReactNode;
  text: string;
} | null {
  const id = `${event.type}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  switch (event.type) {
    case "planning_start":
      return {
        id, status: "pending",
        icon: <Sparkles size={14} />,
        text: `Drafting the week (${event.days} ${event.days === 1 ? "day" : "days"}, ${event.slots.join(" + ")})`,
      };
    case "planning_done":
      return {
        id, status: "done",
        icon: <Check size={14} />,
        text: `Drafted "${event.plan_name}" — ${event.meals_proposed} meals, ${event.recipes_to_generate} new recipes to create`,
      };
    case "recipe_start":
      return {
        id, status: "pending",
        icon: <Sparkles size={14} />,
        text: `Generating recipe: ${event.prompt}`,
      };
    case "recipe_done":
      return {
        id, status: "done",
        icon: <Check size={14} />,
        text: `Made "${event.name}" · ${event.duration}s`,
      };
    case "recipe_failed":
      return {
        id, status: "failed",
        icon: <X size={14} />,
        text: `Failed: ${event.prompt} (${event.error})`,
      };
    case "persisting":
      return {
        id, status: "pending",
        icon: <Save size={14} />,
        text: "Saving the plan and new recipes…",
      };
    case "complete":
      return {
        id, status: "done",
        icon: <Check size={14} />,
        text: `Done — plan ready (${event.total_duration}s total)`,
      };
    case "error":
      return {
        id, status: "failed",
        icon: <X size={14} />,
        text: event.message,
      };
  }
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
