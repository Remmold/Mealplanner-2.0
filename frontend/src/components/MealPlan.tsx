import { useEffect, useMemo, useState } from "react";
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

  // AI weekly generator
  const [genOpen, setGenOpen] = useState(false);
  const [genPrompt, setGenPrompt] = useState("");
  const [genStart, setGenStart] = useState(isoDate(new Date()));
  const [genDays, setGenDays] = useState(7);
  const [genServings, setGenServings] = useState(4);
  const [genSlots, setGenSlots] = useState<Record<Slot, boolean>>({
    breakfast: false, lunch: false, dinner: true,
  });
  const [generating, setGenerating] = useState(false);
  const [genElapsed, setGenElapsed] = useState(0);

  useEffect(() => {
    reloadPlans();
    fetchRecipes().then(setRecipes).catch((e) => setError(String(e)));
  }, []);

  // Refresh when the chat agent mutates anything
  useEffect(() => {
    return onDataChanged((kind) => {
      if (kind === "*" || kind === "meal_plans") reloadPlans();
      if (kind === "*" || kind === "recipes") fetchRecipes().then(setRecipes).catch(() => {});
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
    const slots = (Object.keys(genSlots) as Slot[]).filter((s) => genSlots[s]);
    if (slots.length === 0) { setError("Pick at least one slot"); return; }
    if (!genPrompt.trim()) { setError("Describe what kind of week you want"); return; }
    setGenerating(true); setError(""); setGenElapsed(0);
    const t0 = Date.now();
    const timer = setInterval(() => setGenElapsed(Math.round((Date.now() - t0) / 1000)), 1000);
    try {
      const plan = await generateMealPlan({
        prompt: genPrompt.trim(),
        start_date: genStart,
        days: genDays,
        servings: genServings,
        slots,
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

      {error && <div className="error">{error}</div>}

      {/* Plans bar */}
      <div className="col gap-2">
        <h3 className="muted small" style={{ textTransform: "uppercase", letterSpacing: "0.05em", margin: 0 }}>
          Your plans
        </h3>
        <div className="row wrap gap-2">
          <button onClick={newPlan} className="btn btn-primary btn-sm">+ New plan</button>
          <button onClick={() => setGenOpen(true)} className="btn btn-accent btn-sm">✦ Generate week with AI</button>
          {plans.map((p) => (
            <span key={p.id} className={`chip ${p.id === activeId ? "chip-active" : ""}`}>
              <span onClick={() => loadPlan(p)}>{p.name}</span>
              <span className="chip-x" onClick={(e) => { e.stopPropagation(); removePlan(p.id); }}>×</span>
            </span>
          ))}
          {plans.length === 0 && <span className="muted small">No plans yet.</span>}
        </div>
      </div>

      {/* Editor card */}
      <div className="card">
        <div className="row gap-3 wrap">
          <input
            className="input-title flex-1"
            value={planName}
            onChange={(e) => { setPlanName(e.target.value); setDirty(true); }}
            style={{ minWidth: 240 }}
          />
          <label className="field">
            Start date
            <input
              type="date"
              className="input"
              value={startDate}
              onChange={(e) => { setStartDate(e.target.value); setDirty(true); }}
              style={{ width: "auto" }}
            />
          </label>
          <button
            onClick={savePlan}
            disabled={!dirty && activeId !== null}
            className="btn btn-primary"
          >
            {activeId ? "Save" : "Create"}
          </button>
          <button
            onClick={generateShopping}
            disabled={!activeId || dirty}
            className="btn btn-accent"
          >
            🛒 Shopping list
          </button>
        </div>

        <div className="divider" />

        <div style={{ overflowX: "auto" }}>
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
                            <div style={{ fontWeight: 500, marginBottom: 2 }}>{e.recipe_name}</div>
                            <div className="row gap-2">
                              <input
                                type="number" min={1} value={e.portions}
                                onChange={(ev) => updateEntryPortions(e.id, Number(ev.target.value) || 1)}
                                className="input"
                                style={{ width: 50, padding: "2px 4px", fontSize: 12 }}
                              />
                              <span className="tiny muted">portions</span>
                              <button onClick={() => removeEntry(e.id)} className="icon-btn" style={{ marginLeft: "auto", width: 22, height: 22, fontSize: 12 }}>×</button>
                            </div>
                          </div>
                        ))}
                        <button onClick={() => setPickerCell({ date, slot })} className="cell-add">+</button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* AI weekly plan generator modal */}
      {genOpen && (
        <div className="modal-backdrop" onClick={() => !generating && setGenOpen(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 520 }}>
            <h3>✦ Generate a week</h3>
            <p className="small muted">
              Describe what you want — diet, vibe, constraints. The kitchen will draft a plan and create
              any new recipes it needs.
            </p>

            <div className="col-2 mt-3">
              <label className="field" style={{ flexDirection: "column", alignItems: "flex-start" }}>
                <span className="small">Brief</span>
                <textarea
                  className="textarea"
                  placeholder="e.g. Mediterranean-leaning week, vegetarian Mondays, family of 4, batch-cook on Sunday"
                  value={genPrompt}
                  onChange={(e) => setGenPrompt(e.target.value)}
                  rows={3}
                  disabled={generating}
                  style={{ width: "100%" }}
                />
              </label>

              <div className="row gap-3 wrap">
                <label className="field">
                  Start
                  <input
                    type="date" className="input"
                    value={genStart}
                    onChange={(e) => setGenStart(e.target.value)}
                    disabled={generating}
                  />
                </label>
                <label className="field">
                  Days
                  <input
                    type="number" min={1} max={14}
                    className="input input-num"
                    value={genDays}
                    onChange={(e) => setGenDays(Math.max(1, Math.min(14, Number(e.target.value) || 7)))}
                    disabled={generating}
                  />
                </label>
                <label className="field">
                  Servings
                  <input
                    type="number" min={1}
                    className="input input-num"
                    value={genServings}
                    onChange={(e) => setGenServings(Math.max(1, Number(e.target.value) || 4))}
                    disabled={generating}
                  />
                </label>
              </div>

              <div className="row gap-3">
                <span className="small muted">Slots:</span>
                {(["breakfast", "lunch", "dinner"] as Slot[]).map((s) => (
                  <label key={s} className="field" style={{ textTransform: "capitalize" }}>
                    <input
                      type="checkbox"
                      checked={genSlots[s]}
                      onChange={() => setGenSlots((prev) => ({ ...prev, [s]: !prev[s] }))}
                      disabled={generating}
                    />
                    {s}
                  </label>
                ))}
              </div>
            </div>

            <div className="row gap-2 mt-4">
              <button onClick={runWeeklyGenerator} disabled={generating} className="btn btn-accent flex-1">
                {generating ? "Drafting your week..." : "Generate"}
              </button>
              <button onClick={() => setGenOpen(false)} disabled={generating} className="btn btn-ghost">
                Cancel
              </button>
            </div>
            {generating && (
              <div className="card-soft mt-3">
                <div className="row gap-2">
                  <div className="chat-typing"><span></span><span></span><span></span></div>
                  <div className="flex-1">
                    <div style={{ fontWeight: 500 }}>Drafting your week…</div>
                    <div className="tiny muted">
                      {genElapsed}s elapsed · planner runs first, then recipes generate in parallel. Usually 30–90s total.
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Recipe picker modal */}
      {pickerCell && (
        <div className="modal-backdrop" onClick={() => setPickerCell(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Pick a recipe</h3>
            <p className="small muted">{formatDay(pickerCell.date)} · <span style={{ textTransform: "capitalize" }}>{pickerCell.slot}</span></p>
            {recipes.length === 0 && <div className="empty">No saved recipes.</div>}
            <div className="col-2 mt-3">
              {recipes.map((r) => (
                <div key={r.id} onClick={() => addRecipeToCell(r)} className="recipe-card">
                  <div style={{ fontWeight: 600 }}>{r.name}</div>
                  <div className="tiny muted">{r.servings} servings · {r.ingredients.length} ingredients</div>
                </div>
              ))}
            </div>
            <button onClick={() => setPickerCell(null)} className="btn btn-ghost mt-3">Cancel</button>
          </div>
        </div>
      )}

      {/* Generated shopping list */}
      {shopping && (
        <div className="card">
          <h3>Shopping list</h3>
          {shopping.categories.length === 0 && <div className="empty">No items.</div>}
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
        </div>
      )}
    </div>
  );
}
