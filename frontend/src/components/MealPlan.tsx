import { useCallback, useEffect, useMemo, useState } from "react";
import { BookOpen, Check, ChevronLeft, ChevronRight, Plus, Save, ShoppingCart, Sparkles, X } from "lucide-react";
import type { ReactNode } from "react";
import {
  fetchMeals,
  createMeal,
  updateMeal,
  deleteMeal,
  mealsShoppingList,
  fetchRecipes,
  generateMealPlan,
  fetchCalendarConflicts,
  navigateTo,
  onDataChanged,
  onNavigate,
  type CalendarConflict,
  type GenerateEvent,
  type MealEntry,
  type Recipe,
  type ShoppingList,
} from "../api";
import { fetchProfile, type ProfileSummary } from "../lib/auth-api";
import { Button, Card, Empty, ErrorBanner, Field, IconButton, Input, Modal, Pill, Textarea } from "./ui";
import DateRangePicker from "./DateRangePicker";

const SLOTS = ["breakfast", "lunch", "dinner"] as const;
type Slot = typeof SLOTS[number];

function isoDate(d: Date): string {
  // Local components, not toISOString — toISOString returns UTC, which in
  // any timezone east of UTC turns "today at 00:00 local" into yesterday.
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
function addDays(iso: string, n: number): string {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + n);
  return isoDate(d);
}
function formatDayName(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString(undefined, { weekday: "long" });
}
function formatDayShort(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
function formatDay(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString(undefined, {
    weekday: "short", month: "short", day: "numeric",
  });
}
function mondayOf(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  const dow = d.getDay(); // 0=Sun .. 6=Sat
  const offset = dow === 0 ? -6 : 1 - dow;
  d.setDate(d.getDate() + offset);
  return isoDate(d);
}
function firstGridMonday(year: number, monthIdx: number): string {
  return mondayOf(isoDate(new Date(year, monthIdx, 1)));
}
function monthLabel(year: number, monthIdx: number): string {
  return new Date(year, monthIdx, 1).toLocaleDateString(undefined, {
    month: "long", year: "numeric",
  });
}
function dayNumber(iso: string): number {
  return new Date(iso + "T00:00:00").getDate();
}
function inMonth(iso: string, year: number, monthIdx: number): boolean {
  const d = new Date(iso + "T00:00:00");
  return d.getFullYear() === year && d.getMonth() === monthIdx;
}

const TODAY_ISO = isoDate(new Date());
const TODAY_MONDAY = mondayOf(TODAY_ISO);
const TODAY = new Date();
const TODAY_YEAR = TODAY.getFullYear();
const TODAY_MONTH = TODAY.getMonth();


export default function MealPlan() {
  // Month-grid calendar. visibleMonth anchors the grid; meals are fetched
  // for the full visible grid (first Mon ... +6 weeks) so cells outside
  // the current month still render their pills.
  const [visibleMonth, setVisibleMonth] = useState<{ year: number; month: number }>({
    year: TODAY_YEAR, month: TODAY_MONTH,
  });
  const [meals, setMeals] = useState<MealEntry[]>([]);
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const [pickerCell, setPickerCell] = useState<{ date: string; slot: Slot } | null>(null);
  const [pickerQuery, setPickerQuery] = useState("");

  const [shopping, setShopping] = useState<ShoppingList | null>(null);
  const [shoppingBusy, setShoppingBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Generator wizard state (legacy path; still creates a plan + entries,
  // but those entries land on the flat calendar same as everything else).
  const [genOpen, setGenOpen] = useState(false);
  const [genStep, setGenStep] = useState<0 | 1 | 2>(0);  // 0=basics, 1=brief, 2=conflicts
  const [conflicts, setConflicts] = useState<CalendarConflict[]>([]);
  const [replaceIds, setReplaceIds] = useState<Set<string>>(new Set());
  const [checkingConflicts, setCheckingConflicts] = useState(false);
  const [genPrompt, setGenPrompt] = useState("");
  const [genStart, setGenStart] = useState(TODAY_MONDAY);
  const [genEnd, setGenEnd] = useState(addDays(TODAY_MONDAY, 6));
  const [genServings, setGenServings] = useState(4);
  // Always dinner now — the system is dinner-focused per household preference.
  const enabledSlots: Set<Slot> = useMemo(() => new Set<Slot>(["dinner"]), []);
  const [generating, setGenerating] = useState(false);
  const [genElapsed, setGenElapsed] = useState(0);

  interface FeedItem {
    id: string;
    status: "pending" | "done" | "failed";
    icon: ReactNode;
    text: string;
  }
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [profile, setProfile] = useState<ProfileSummary | null>(null);

  // 6×7 grid of date strings — first Mon of the visible month's week,
  // then 41 days after. Cells outside the active month are dimmed.
  const gridStart = useMemo(
    () => firstGridMonday(visibleMonth.year, visibleMonth.month),
    [visibleMonth],
  );
  const gridDates = useMemo(
    () => Array.from({ length: 42 }, (_, i) => addDays(gridStart, i)),
    [gridStart],
  );
  const gridEnd = gridDates[gridDates.length - 1];

  // Slot prefs for the day-detail modal. Empty = show all three. Any meal
  // in a hidden slot still shows so the user can find/remove it.
  const visibleSlotsForDay = useCallback(
    (date: string): Slot[] => {
      const pref = profile?.visible_slots ?? [];
      const slotsWithMeals = new Set(
        meals.filter((m) => m.plan_date === date).map((m) => m.slot ?? ""),
      );
      if (pref.length === 0) return SLOTS.filter((s) => true || slotsWithMeals.has(s));
      const allowed = new Set(pref);
      return SLOTS.filter((s) => allowed.has(s) || slotsWithMeals.has(s));
    },
    [profile?.visible_slots, meals],
  );

  const isCurrentMonth =
    visibleMonth.year === TODAY_YEAR && visibleMonth.month === TODAY_MONTH;
  const monthHeading = monthLabel(visibleMonth.year, visibleMonth.month);

  // ---------------------------------------------------------------
  // Load meals for the visible grid + cross-tab sync
  // ---------------------------------------------------------------

  const reloadMeals = useCallback(async (start: string, end: string) => {
    setBusy(true);
    try {
      const list = await fetchMeals(start, end);
      setMeals(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { void reloadMeals(gridStart, gridEnd); }, [gridStart, gridEnd, reloadMeals]);

  useEffect(() => {
    fetchRecipes().then(setRecipes).catch((e) => setError(String(e)));
    fetchProfile().then((p) => {
      setProfile(p);
      if (p.family_size && p.family_size > 0) setGenServings(p.family_size);
    }).catch(() => { /* sparse profile is fine */ });
  }, []);

  useEffect(() => {
    return onDataChanged((kind) => {
      if (kind === "*" || kind === "meal_plans" || kind === "meals") {
        void reloadMeals(gridStart, gridEnd);
      }
      if (kind === "*" || kind === "recipes") {
        fetchRecipes().then(setRecipes).catch(() => {});
      }
      if (kind === "*") fetchProfile().then(setProfile).catch(() => {});
    });
  }, [gridStart, gridEnd, reloadMeals]);

  // ---------------------------------------------------------------
  // Chat-driven navigation
  // ---------------------------------------------------------------

  useEffect(() => {
    return onNavigate((intent) => {
      if (intent.tab !== "plan") return;
      if (intent.openGenerator) openGenerator();
      if (intent.week_start) {
        const d = new Date(intent.week_start + "T00:00:00");
        setVisibleMonth({ year: d.getFullYear(), month: d.getMonth() });
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---------------------------------------------------------------
  // Calendar interactions — each writes immediately
  // ---------------------------------------------------------------

  function mealsAt(date: string, slot: Slot): MealEntry[] {
    return meals.filter((m) => m.plan_date === date && m.slot === slot);
  }
  function mealsOnDay(date: string): MealEntry[] {
    return meals.filter((m) => m.plan_date === date);
  }

  async function addRecipeToCell(recipe: Recipe) {
    if (!pickerCell) return;
    const date = pickerCell.date;
    const slot = pickerCell.slot;
    setPickerCell(null);
    setPickerQuery("");
    try {
      const saved = await createMeal({
        recipe_id: recipe.id,
        plan_date: date,
        slot,
        portions: recipe.servings,
      });
      setMeals((prev) => [...prev, saved]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function removeMeal(id: string) {
    // Optimistic: drop from UI immediately, roll back on error.
    const snapshot = meals;
    setMeals((prev) => prev.filter((m) => m.id !== id));
    try { await deleteMeal(id); }
    catch (e) {
      setMeals(snapshot);
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function changePortions(id: string, portions: number) {
    const next = Math.max(0.25, portions);
    setMeals((prev) => prev.map((m) => (m.id === id ? { ...m, portions: next } : m)));
    try { await updateMeal(id, { portions: next }); }
    catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      void reloadMeals(gridStart, gridEnd);
    }
  }

  // ---------------------------------------------------------------
  // Toolbar
  // ---------------------------------------------------------------

  function jumpMonth(delta: number) {
    setVisibleMonth((vm) => {
      const m = vm.month + delta;
      const yearShift = Math.floor(m / 12);
      const newMonth = ((m % 12) + 12) % 12;
      return { year: vm.year + yearShift, month: newMonth };
    });
  }

  function goToToday() {
    setVisibleMonth({ year: TODAY_YEAR, month: TODAY_MONTH });
  }

  async function generateShoppingForWeekOf(dateIso: string) {
    setShoppingBusy(true);
    try {
      const monday = mondayOf(dateIso);
      setShopping(await mealsShoppingList(monday, addDays(monday, 6)));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setShoppingBusy(false);
    }
  }

  // ---------------------------------------------------------------
  // AI generator wizard (writes through the legacy plan endpoint but the
  // resulting entries appear on the flat calendar via /meals)
  // ---------------------------------------------------------------

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

  function openGenerator() {
    // Default to "this week starting Monday" so the generator targets the
    // most likely week the user wants regardless of which month they're
    // viewing in the calendar.
    setGenStart(TODAY_MONDAY);
    setGenEnd(addDays(TODAY_MONDAY, 6));
    setGenStep(0);
    setConflicts([]);
    setReplaceIds(new Set());
    setError("");
    setGenOpen(true);
  }
  function closeGenerator() { if (!generating) setGenOpen(false); }

  // Pre-flight: before generating, check the chosen range for days already
  // planned. If any exist, route to the keep/replace step; otherwise generate
  // straight away. Default is KEEP everything (never double-book).
  async function prepareGenerate() {
    if (Array.from(enabledSlots).length === 0) { setError("Pick at least one meal slot"); return; }
    if (genRangeError) { setError(genRangeError); return; }
    setCheckingConflicts(true); setError("");
    try {
      const found = await fetchCalendarConflicts(genStart, genEnd, Array.from(enabledSlots));
      if (found.length > 0) {
        setConflicts(found);
        setReplaceIds(new Set());   // default: keep every occupied day
        setGenStep(2);
      } else {
        await runWeeklyGenerator([]);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setCheckingConflicts(false);
    }
  }

  function toggleReplace(entryId: string, replace: boolean) {
    setReplaceIds((prev) => {
      const next = new Set(prev);
      if (replace) next.add(entryId); else next.delete(entryId);
      return next;
    });
  }
  function keepAll() { setReplaceIds(new Set()); }
  function replaceAll() { setReplaceIds(new Set(conflicts.map((c) => c.entry_id))); }

  async function runWeeklyGenerator(replaceEntryIds: string[]) {
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
          replace_entry_ids: replaceEntryIds,
        },
        (event) => {
          const item = buildFeedItem(event);
          if (item) setFeed((prev) => [...prev, item]);
        },
      );
      // Jump the calendar to the month containing the generated plan.
      const startD = new Date(plan.start_date + "T00:00:00");
      setVisibleMonth({ year: startD.getFullYear(), month: startD.getMonth() });
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

  // =================================================================
  // Render
  // =================================================================

  return (
    <div className="col gap-4">
      <ErrorBanner>{error}</ErrorBanner>

      <div className="plan-toolbar">
        <div className="row gap-1 items-center">
          <IconButton onClick={() => jumpMonth(-1)} title="Previous month" aria-label="Previous month">
            <ChevronLeft size={18} />
          </IconButton>
          <div className="plan-toolbar-week">
            <span className="fw-600">{monthHeading}</span>
            {isCurrentMonth && <span className="tiny muted ml-1">· this month</span>}
          </div>
          <IconButton onClick={() => jumpMonth(1)} title="Next month" aria-label="Next month">
            <ChevronRight size={18} />
          </IconButton>
          {!isCurrentMonth && (
            <Button onClick={goToToday} variant="ghost" size="sm" className="ml-2">Today</Button>
          )}
          {busy && <span className="tiny muted ml-2">Loading…</span>}
        </div>

        <div className="row gap-2 ml-auto">
          <Button onClick={openGenerator} variant="accent" size="sm">
            <Sparkles size={14} /> Generate week with AI
          </Button>
          <Button
            onClick={() => generateShoppingForWeekOf(TODAY_ISO)}
            disabled={meals.length === 0 || shoppingBusy}
            variant="primary"
            size="sm"
          >
            <ShoppingCart size={14} /> {shoppingBusy ? "Building…" : "Shopping (this week)"}
          </Button>
        </div>
      </div>

      <div className="month-grid">
        <div className="month-header">
          {(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]).map((d) => (
            <div key={d} className="month-header-day">{d}</div>
          ))}
        </div>
        <div className="month-body">
          {gridDates.map((date) => {
            const cellMeals = mealsOnDay(date);
            const dinner = cellMeals[0] ?? null;   // dinner-only world: one meal per day
            const isToday = date === TODAY_ISO;
            const inThisMonth = inMonth(date, visibleMonth.year, visibleMonth.month);
            const dayNum = dayNumber(date);
            return (
              <button
                key={date}
                type="button"
                onClick={() => {
                  if (dinner) setSelectedDay(date);
                  else setPickerCell({ date, slot: "dinner" });
                }}
                className={
                  "month-cell" +
                  (isToday ? " month-cell-today" : "") +
                  (inThisMonth ? "" : " month-cell-outside") +
                  (dinner ? " month-cell-has-meal" : "")
                }
              >
                <div className="month-cell-day">
                  {dayNum}
                  {dayNum === 1 && (
                    <span className="month-cell-month-label">
                      {new Date(date + "T00:00:00").toLocaleDateString(undefined, { month: "short" })}
                    </span>
                  )}
                </div>
                {dinner ? (
                  <div className="month-cell-card">
                    {dinner.image_path ? (
                      <img
                        src={`/api/recipe-images/${dinner.image_path}`}
                        alt=""
                        className="month-cell-img"
                        draggable={false}
                      />
                    ) : (
                      <div className="month-cell-img month-cell-img-placeholder" />
                    )}
                    <div className="month-cell-card-name">{dinner.recipe_name}</div>
                    {cellMeals.length > 1 && (
                      <div className="month-cell-more">+{cellMeals.length - 1} more</div>
                    )}
                  </div>
                ) : (
                  inThisMonth && <div className="month-cell-empty">+</div>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Day-detail modal — dinner-focused; lists the day's meals + lets you
          tweak or add another. */}
      <Modal open={!!selectedDay} onClose={() => setSelectedDay(null)}>
        {selectedDay && (() => {
          const dayMeals = mealsOnDay(selectedDay);
          return (
            <>
              <div className="row gap-2 items-baseline">
                <h3 className="m-0 flex-1">{formatDay(selectedDay)}</h3>
                <Button
                  onClick={() => generateShoppingForWeekOf(selectedDay)}
                  variant="ghost"
                  size="sm"
                >
                  <ShoppingCart size={12} /> Week shopping
                </Button>
              </div>
              <div className="col gap-2 mt-3">
                {dayMeals.map((m) => (
                  <div key={m.id} className="cell-recipe">
                    <div className="cell-recipe-name">{m.recipe_name}</div>
                    <div className="cell-recipe-meta">
                      <Input
                        type="number" min={1} value={m.portions}
                        onChange={(ev) => changePortions(m.id, Number(ev.target.value) || 1)}
                        className="input-mini"
                      />
                      <span className="tiny muted">portions</span>
                      <Button
                        onClick={() => navigateTo({ tab: "recipe", recipe_id: m.recipe_id })}
                        variant="ghost"
                        size="xs"
                        className="ml-auto"
                      >
                        <BookOpen size={12} /> View recipe
                      </Button>
                      <IconButton
                        onClick={() => removeMeal(m.id)}
                        className="icon-btn-sm"
                        aria-label="Remove"
                      >
                        <X size={11} />
                      </IconButton>
                    </div>
                  </div>
                ))}
                <button
                  onClick={() => setPickerCell({ date: selectedDay, slot: "dinner" })}
                  className="cell-add"
                >
                  <Plus size={12} /> add another dinner
                </button>
              </div>
            </>
          );
        })()}
      </Modal>

      {genOpen && (
        <div className="plan-shell" role="dialog" aria-modal>
          <div className="brand auth-brand plan-shell-brand">
            <span className="brand-mark">Plan this week</span>
            <span className="brand-tag">Hearth drafts a plan and a shopping list</span>
          </div>

          <Card className="plan-shell-card">
            <div className="tour-dots" aria-hidden>
              {[0, 1].map((i) => (
                <span key={i} className={"tour-dot" + (i === Math.min(genStep, 1) ? " tour-dot-active" : "")} />
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
                <h2 className="m-0">Anything special this week?</h2>
                <p className="muted m-0">
                  Hearth respects your profile every time — only mention what changes <em>this</em> week.
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

            {genStep === 2 && (
              <div className="col-2">
                <h2 className="m-0">Some days are already planned</h2>
                <p className="muted m-0">
                  Kept days are left exactly as they are — Hearth plans around them.
                  Choose <em>Replace</em> for any you'd like it to overwrite.
                </p>
                <div className="row gap-2 items-center">
                  <span className="tiny muted flex-1">
                    {conflicts.length} planned day{conflicts.length === 1 ? "" : "s"}
                  </span>
                  <Button
                    size="xs"
                    variant={replaceIds.size === 0 ? "primary" : "ghost"}
                    onClick={keepAll}
                    disabled={generating}
                  >
                    Keep all
                  </Button>
                  <Button
                    size="xs"
                    variant={replaceIds.size === conflicts.length ? "primary" : "ghost"}
                    onClick={replaceAll}
                    disabled={generating}
                  >
                    Replace all
                  </Button>
                </div>
                <div className="col gap-2">
                  {conflicts.map((c) => {
                    const replace = replaceIds.has(c.entry_id);
                    return (
                      <div key={c.entry_id} className="row gap-2 items-center pick-row">
                        <div className="flex-1">
                          <div className="fw-500">{formatDay(c.plan_date)} · {c.slot}</div>
                          <div className="tiny muted">{c.recipe_name ?? "Planned meal"}</div>
                        </div>
                        <Button
                          size="xs"
                          variant={replace ? "ghost" : "primary"}
                          onClick={() => toggleReplace(c.entry_id, false)}
                          disabled={generating}
                        >
                          Keep
                        </Button>
                        <Button
                          size="xs"
                          variant={replace ? "primary" : "ghost"}
                          onClick={() => toggleReplace(c.entry_id, true)}
                          disabled={generating}
                        >
                          Replace
                        </Button>
                      </div>
                    );
                  })}
                </div>
                <p className="tiny muted m-0">
                  {replaceIds.size === 0
                    ? "Keeping every planned day."
                    : `Replacing ${replaceIds.size} of ${conflicts.length}.`}
                </p>
              </div>
            )}

            <div className="row gap-2 mt-4">
              {genStep > 0 ? (
                <Button
                  variant="ghost"
                  onClick={() => setGenStep(genStep === 2 ? 1 : 0)}
                  disabled={generating || checkingConflicts}
                >
                  Back
                </Button>
              ) : (
                <Button variant="ghost" onClick={closeGenerator} disabled={generating}>
                  Cancel
                </Button>
              )}
              {genStep === 0 && (
                <Button
                  variant="primary"
                  onClick={() => setGenStep(1)}
                  disabled={generating || genRangeError !== null}
                  className="flex-1"
                >
                  Continue
                </Button>
              )}
              {genStep === 1 && (
                <Button
                  variant="accent"
                  onClick={prepareGenerate}
                  disabled={generating || checkingConflicts}
                  className="flex-1"
                >
                  {checkingConflicts ? "Checking your calendar…" : "Generate this week's plan"}
                </Button>
              )}
              {genStep === 2 && (
                <Button
                  variant="accent"
                  onClick={() => runWeeklyGenerator(Array.from(replaceIds))}
                  disabled={generating}
                  className="flex-1"
                >
                  {generating ? "Drafting your week..." : "Generate this week's plan"}
                </Button>
              )}
            </div>

            {error && <div className="mt-3"><ErrorBanner>{error}</ErrorBanner></div>}

            {(generating || feed.length > 0) && (
              <Card variant="soft" className="mt-3 gen-feed">
                <div className="gen-feed-header">
                  {generating && (
                    <div className="chat-typing"><span></span><span></span><span></span></div>
                  )}
                  <div className="flex-1">
                    <div className="fw-500">
                      {generating ? "Drafting your week" : "Generator stopped"}
                    </div>
                    <div className="tiny muted">
                      {generating ? `${genElapsed}s elapsed` : `last run · ${genElapsed}s`}
                    </div>
                  </div>
                </div>
                {feed.length > 0 && (
                  <ul className="gen-feed-list">
                    {feed.map((item) => (
                      <li key={item.id} className={`gen-feed-item gen-feed-${item.status}`}>
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

      <Modal open={!!pickerCell} onClose={() => { setPickerCell(null); setPickerQuery(""); }}>
        {pickerCell && (() => {
          const slot = pickerCell.slot;
          const q = pickerQuery.trim().toLowerCase();
          const filtered = recipes.filter((r) => !q || r.name.toLowerCase().includes(q));
          const sorted = [...filtered].sort((a, b) => {
            const rank = (r: Recipe) =>
              r.meal_type === slot ? 0 : r.meal_type == null ? 1 : 2;
            return rank(a) - rank(b);
          });
          return (
            <>
              <h3>Pick a recipe</h3>
              <p className="small muted">
                {formatDay(pickerCell.date)} · <span className="capitalize">{slot}</span>
              </p>
              <Input
                placeholder={`Search ${recipes.length} recipes…`}
                value={pickerQuery}
                onChange={(e) => setPickerQuery(e.target.value)}
                autoFocus
                className="mt-2"
              />
              {recipes.length === 0 && <Empty>No saved recipes.</Empty>}
              {recipes.length > 0 && sorted.length === 0 && (
                <Empty>No recipes match "{pickerQuery}".</Empty>
              )}
              <div className="col-2 mt-3">
                {sorted.map((r) => (
                  <div key={r.id} onClick={() => addRecipeToCell(r)} className="recipe-card horizontal">
                    {r.image_path ? (
                      <img src={`/api/recipe-images/${r.image_path}`} alt="" className="recipe-thumb" />
                    ) : (
                      <div className="recipe-thumb" />
                    )}
                    <div className="flex-1">
                      <div className="row gap-2 items-center">
                        <span className="fw-600">{r.name}</span>
                        {r.meal_type && (
                          <Pill className={r.meal_type === slot ? "pill-match" : undefined}>
                            {r.meal_type}
                          </Pill>
                        )}
                      </div>
                      <div className="tiny muted">
                        {r.servings} servings ·{" "}
                        {r.ingredients.filter((i) => !i.from_pantry).length} to buy
                        {r.ingredients.some((i) => i.from_pantry) && (
                          <span> · {r.ingredients.filter((i) => i.from_pantry).length} pantry</span>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <Button onClick={() => { setPickerCell(null); setPickerQuery(""); }} variant="ghost" className="mt-3">
                Cancel
              </Button>
            </>
          );
        })()}
      </Modal>

      {shopping && (
        <Card>
          <div className="row gap-2 items-center">
            <h3 className="m-0 flex-1">Shopping list</h3>
            <IconButton onClick={() => setShopping(null)} aria-label="Close shopping list">
              <X size={14} />
            </IconButton>
          </div>
          {shopping.categories.length === 0 && shopping.pantry_check.length === 0 && (
            <Empty>No items.</Empty>
          )}
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
          {shopping.pantry_check.length > 0 && (
            <details className="pantry-check mt-3">
              <summary>
                Check pantry · {shopping.pantry_check.length} staple{shopping.pantry_check.length === 1 ? "" : "s"} the week uses
              </summary>
              {shopping.pantry_check.map((item) => (
                <div key={item.fdc_id} className="shop-row pantry-row">
                  <span className="flex-1">{item.name}</span>
                  <span className="shop-qty tiny muted">{item.display_quantity} {item.display_unit}</span>
                </div>
              ))}
            </details>
          )}
        </Card>
      )}
    </div>
  );
}


function buildFeedItem(event: GenerateEvent): {
  id: string;
  status: "pending" | "done" | "failed";
  icon: ReactNode;
  text: string;
} | null {
  const id = `${event.type}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  switch (event.type) {
    case "planning_start":
      return { id, status: "pending", icon: <Sparkles size={14} />,
        text: `Drafting the week (${event.days} ${event.days === 1 ? "day" : "days"}, ${event.slots.join(" + ")})` };
    case "planning_done":
      return { id, status: "done", icon: <Check size={14} />,
        text: `Drafted "${event.plan_name}" — ${event.meals_proposed} meals, ${event.recipes_to_generate} new recipes to create` };
    case "recipe_start":
      return { id, status: "pending", icon: <Sparkles size={14} />,
        text: `Generating recipe: ${event.prompt}${event.reason ? ` (${event.reason})` : ""}` };
    case "recipe_done":
      return { id, status: "done", icon: <Check size={14} />, text: `Made "${event.name}" · ${event.duration}s` };
    case "recipe_failed":
      return { id, status: "failed", icon: <X size={14} />, text: `Failed: ${event.prompt} (${event.error})` };
    case "persisting":
      return { id, status: "pending", icon: <Save size={14} />, text: "Saving the plan and new recipes…" };
    case "complete":
      return { id, status: "done", icon: <Check size={14} />, text: `Done — plan ready (${event.total_duration}s total)` };
    case "error":
      return { id, status: "failed", icon: <X size={14} />, text: event.message };
  }
}


function ProfileContextCard({ profile }: { profile: ProfileSummary | null }) {
  if (!profile) {
    return <Card variant="soft" className="mt-2"><p className="small muted m-0">Loading your household preferences…</p></Card>;
  }
  const chips: string[] = [];
  if (profile.family_size && profile.family_size > 0) chips.push(`cooking for ${profile.family_size}`);
  profile.dietary.forEach((d) => chips.push(d));
  if (profile.allergies.length > 0) chips.push(`no ${profile.allergies.join(", ")}`);
  if (profile.typical_cook_time_min) chips.push(`~${profile.typical_cook_time_min} min weeknights`);
  profile.cuisines.slice(0, 4).forEach((c) => chips.push(c));
  if (profile.batch_cook_preference && profile.batch_cook_preference !== "none") {
    chips.push(`batch-cook ${profile.batch_cook_preference}`);
  }
  if (chips.length === 0) {
    return (
      <Card variant="soft" className="mt-2">
        <p className="small m-0">Your profile is empty — Hearth will guess from a typical household.</p>
        <p className="tiny muted m-0 mt-1">
          Open the chat and tell it about your preferences. It will remember for next time.
        </p>
      </Card>
    );
  }
  return (
    <Card variant="soft" className="mt-2">
      <p className="tiny muted m-0">Hearth will use what we've learned so far:</p>
      <div className="row wrap gap-2 mt-2">
        {chips.map((c, i) => (<Pill key={i}>{c}</Pill>))}
      </div>
      <p className="tiny muted m-0 mt-2">
        Wrong or missing? Open the chat and tell it — the assistant remembers.
      </p>
    </Card>
  );
}
