import { useEffect, useMemo, useState } from "react";
import {
  fetchMealPlans,
  createMealPlan,
  updateMealPlan,
  deleteMealPlan,
  mealPlanShoppingList,
  fetchRecipes,
  type MealPlan,
  type MealPlanEntry,
  type Recipe,
  type ShoppingList,
} from "../api";

const DAYS = 7;
const SLOTS = ["breakfast", "lunch", "dinner"] as const;
type Slot = typeof SLOTS[number];

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

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

  useEffect(() => {
    reloadPlans();
    fetchRecipes().then(setRecipes).catch((e) => setError(String(e)));
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
        name: planName,
        start_date: startDate,
        entries: entries.map((e) => ({
          recipe_id: e.recipe_id,
          plan_date: e.plan_date,
          slot: e.slot,
          portions: e.portions,
        })),
      };
      let saved: MealPlan;
      if (activeId) {
        saved = await updateMealPlan(activeId, payload);
      } else {
        saved = await createMealPlan(payload.name, payload.start_date, payload.entries);
        setActiveId(saved.id);
      }
      setEntries(saved.entries);
      setDirty(false);
      await reloadPlans();
    } catch (e) { setError(String(e)); }
  }

  async function removePlan(id: string) {
    try {
      await deleteMealPlan(id);
      if (activeId === id) newPlan();
      await reloadPlans();
    } catch (e) { setError(String(e)); }
  }

  async function generateShopping() {
    if (!activeId) { setError("Save the plan before generating a shopping list."); return; }
    try { setShopping(await mealPlanShoppingList(activeId)); }
    catch (e) { setError(String(e)); }
  }

  return (
    <div>
      <h2>Meal Plan</h2>
      {error && <p style={{ color: "red" }}>{error}</p>}

      {/* Plans bar */}
      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap", alignItems: "center" }}>
        <button onClick={newPlan} style={{ padding: "6px 14px", fontWeight: 600 }}>+ New Plan</button>
        {plans.map((p) => (
          <div key={p.id} style={{
            display: "flex", alignItems: "center", gap: 4,
            padding: "4px 10px", borderRadius: 4,
            background: p.id === activeId ? "#333" : "#eee",
            color: p.id === activeId ? "#fff" : "#333", cursor: "pointer",
          }}>
            <span onClick={() => loadPlan(p)}>{p.name}</span>
            <button
              onClick={(e) => { e.stopPropagation(); removePlan(p.id); }}
              style={{
                background: "none", border: "none", cursor: "pointer",
                color: p.id === activeId ? "#ccc" : "#999", fontSize: 14, padding: "0 2px",
              }}
            >x</button>
          </div>
        ))}
      </div>

      {/* Name + start + save */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12 }}>
        <input
          value={planName}
          onChange={(e) => { setPlanName(e.target.value); setDirty(true); }}
          style={{ fontSize: 16, fontWeight: "bold", border: "none", borderBottom: "2px solid #333", padding: 4, flex: 1 }}
        />
        <label style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 4 }}>
          Start:
          <input
            type="date"
            value={startDate}
            onChange={(e) => { setStartDate(e.target.value); setDirty(true); }}
            style={{ padding: 4 }}
          />
        </label>
        <button
          onClick={savePlan}
          disabled={!dirty && activeId !== null}
          style={{
            padding: "6px 16px", fontWeight: 600,
            background: dirty || !activeId ? "#2563eb" : "#ccc",
            color: dirty || !activeId ? "#fff" : "#666",
            border: "none", borderRadius: 4, cursor: dirty || !activeId ? "pointer" : "default",
          }}
        >
          {activeId ? "Save" : "Create"}
        </button>
        <button
          onClick={generateShopping}
          disabled={!activeId || dirty}
          style={{
            padding: "6px 16px", fontWeight: 600,
            background: activeId && !dirty ? "#16a34a" : "#ccc",
            color: activeId && !dirty ? "#fff" : "#666",
            border: "none", borderRadius: 4,
            cursor: activeId && !dirty ? "pointer" : "default",
          }}
        >
          Shopping List
        </button>
      </div>

      {/* Week grid */}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr>
              <th style={{ padding: 6, textAlign: "left", width: 90, background: "#f5f5f5" }}></th>
              {dates.map((d) => (
                <th key={d} style={{ padding: 6, background: "#f5f5f5", borderLeft: "1px solid #ddd", textAlign: "center" }}>
                  {formatDay(d)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {SLOTS.map((slot) => (
              <tr key={slot}>
                <td style={{
                  padding: 6, fontWeight: 600, textTransform: "capitalize",
                  background: "#fafafa", borderTop: "1px solid #ddd",
                }}>{slot}</td>
                {dates.map((date) => {
                  const cellEntries = entriesAt(date, slot);
                  return (
                    <td key={date + slot} style={{
                      padding: 4, verticalAlign: "top", minHeight: 60,
                      borderTop: "1px solid #ddd", borderLeft: "1px solid #eee",
                    }}>
                      {cellEntries.map((e) => (
                        <div key={e.id} style={{
                          background: "#eef6ff", padding: "3px 6px", marginBottom: 2,
                          borderRadius: 3, display: "flex", flexDirection: "column", gap: 2,
                        }}>
                          <div style={{ fontWeight: 500 }}>{e.recipe_name}</div>
                          <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                            <input
                              type="number" min={1} value={e.portions}
                              onChange={(ev) => updateEntryPortions(e.id, Number(ev.target.value) || 1)}
                              style={{ width: 40, padding: 2, fontSize: 12 }}
                            />
                            <span style={{ fontSize: 11 }}>pp</span>
                            <button
                              onClick={() => removeEntry(e.id)}
                              style={{ marginLeft: "auto", padding: "0 6px", fontSize: 11 }}
                            >x</button>
                          </div>
                        </div>
                      ))}
                      <button
                        onClick={() => setPickerCell({ date, slot })}
                        style={{
                          width: "100%", padding: 3, fontSize: 12, marginTop: 2,
                          background: "none", border: "1px dashed #ccc", cursor: "pointer",
                        }}
                      >+</button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Recipe picker modal */}
      {pickerCell && (
        <div
          onClick={() => setPickerCell(null)}
          style={{
            position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
            display: "flex", alignItems: "center", justifyContent: "center", zIndex: 10,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: "#fff", borderRadius: 6, padding: 16, width: 400, maxHeight: "80vh", overflowY: "auto",
            }}
          >
            <h3 style={{ margin: "0 0 8px 0" }}>
              Pick recipe — {formatDay(pickerCell.date)} · {pickerCell.slot}
            </h3>
            {recipes.length === 0 && <p style={{ color: "#999" }}>No saved recipes.</p>}
            {recipes.map((r) => (
              <div
                key={r.id}
                onClick={() => addRecipeToCell(r)}
                style={{
                  padding: 8, borderBottom: "1px solid #f0f0f0", cursor: "pointer",
                }}
              >
                <div style={{ fontWeight: 500 }}>{r.name}</div>
                <div style={{ fontSize: 12, color: "#888" }}>{r.servings} servings · {r.ingredients.length} ingredients</div>
              </div>
            ))}
            <button onClick={() => setPickerCell(null)} style={{ marginTop: 8, padding: "4px 12px" }}>Cancel</button>
          </div>
        </div>
      )}

      {/* Generated shopping list */}
      {shopping && (
        <div style={{ marginTop: 16 }}>
          <h3>Shopping List</h3>
          {shopping.categories.length === 0 && <p style={{ color: "#999" }}>No items.</p>}
          {shopping.categories.map((cat) => (
            <div key={cat.category} style={{ marginBottom: 12 }}>
              <h4 style={{
                margin: "0 0 6px 0", padding: "4px 8px",
                background: "#333", color: "#fff", borderRadius: 4,
              }}>{cat.category}</h4>
              {cat.items.map((item) => (
                <div key={item.fdc_id} style={{
                  display: "flex", gap: 8, padding: "3px 8px",
                  borderBottom: "1px solid #f0f0f0", fontSize: 14,
                }}>
                  <span style={{ flex: 1 }}>{item.name}</span>
                  <span style={{ fontWeight: 600 }}>{item.display_quantity} {item.display_unit}</span>
                  {item.display_unit !== "g" && (
                    <span style={{ fontSize: 12, color: "#999" }}>({Math.round(item.quantity_g)} g)</span>
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
