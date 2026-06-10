import { useCallback, useEffect, useMemo, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { BookOpen, Check, ChefHat, ChevronLeft, ChevronRight, Plus, Sandwich, Save, ShoppingCart, Sparkles, X } from "lucide-react";
import type { ReactNode } from "react";
import {
  fetchMeals,
  createMeal,
  updateMeal,
  deleteMeal,
  mealsShoppingList,
  fetchRecipes,
  generateMealPlan,
  regenerateMealPlan,
  fetchCalendarConflicts,
  navigateTo,
  onDataChanged,
  type CalendarConflict,
  type GenerateEvent,
  type MealEntry,
  type MealPlan,
  type Recipe,
  type ShoppingList,
} from "../api";
import { fetchProfile, type ProfileSummary } from "../lib/auth-api";
import { useEnumLabels } from "../i18n/enums";
import i18n from "../i18n";
import { Button, Card, Chip, Empty, ErrorBanner, Field, IconButton, Input, Modal, Pill, Textarea } from "./ui";
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
  return new Date(iso + "T00:00:00").toLocaleDateString(i18n.language, { weekday: "long" });
}
function formatDayShort(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString(i18n.language, { month: "short", day: "numeric" });
}
function formatDay(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString(i18n.language, {
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
  return new Date(year, monthIdx, 1).toLocaleDateString(i18n.language, {
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


// Chat-driven plan intents (open the wizard, jump to a week). App lifts these
// here as a prop rather than us subscribing to onNavigate directly: the chat
// can fire an intent while we're unmounted on another tab, and by the time we
// mounted and subscribed the one-shot event would already be gone. As a prop
// it's set on our very first render, so it survives the tab switch.
export interface PlanIntent {
  openGenerator?: boolean;
  week_start?: string;
}

export default function MealPlan({
  pendingIntent,
  onIntentConsumed,
}: {
  pendingIntent: PlanIntent | null;
  onIntentConsumed: () => void;
}) {
  const { t } = useTranslation();
  const el = useEnumLabels();
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
  // fdc_ids ticked off on the current list. Persisted per-device, keyed by the
  // shopping date-range (see SHOP_CHECKS_KEY), so checking items off survives
  // reloads / closing the plan — useful while actually shopping.
  const SHOP_CHECKS_KEY = "mealplanner.mealplanShopChecks.v1";
  const [shopChecked, setShopChecked] = useState<Set<number>>(new Set());
  const [shoppingBusy, setShoppingBusy] = useState(false);
  // "Shopping list…" range picker (mirrors the AI wizard's date step, but just
  // consolidates the meals already on the calendar for the chosen days).
  const [shopOpen, setShopOpen] = useState(false);
  const [shopStart, setShopStart] = useState(TODAY_MONDAY);
  const [shopEnd, setShopEnd] = useState(addDays(TODAY_MONDAY, 6));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Generator wizard state (legacy path; still creates a plan + entries,
  // but those entries land on the flat calendar same as everything else).
  const [genOpen, setGenOpen] = useState(false);
  const [genStep, setGenStep] = useState<0 | 1 | 2 | 3>(0);  // 0=basics 1=brief 2=conflicts 3=review
  const [conflicts, setConflicts] = useState<CalendarConflict[]>([]);
  const [replaceIds, setReplaceIds] = useState<Set<string>>(new Set());
  const [checkingConflicts, setCheckingConflicts] = useState(false);
  const [reviewPlan, setReviewPlan] = useState<MealPlan | null>(null);
  const [flaggedIds, setFlaggedIds] = useState<Set<string>>(new Set());
  const [regenerating, setRegenerating] = useState(false);
  const [genPrompt, setGenPrompt] = useState("");
  const [genStart, setGenStart] = useState(TODAY_MONDAY);
  const [genEnd, setGenEnd] = useState(addDays(TODAY_MONDAY, 6));
  const [genServings, setGenServings] = useState(4);
  // Day offsets (0 = genStart) the user flagged as "just me eating" — sized for
  // one and filled leftover-first by the planner.
  const [soloDays, setSoloDays] = useState<Set<number>>(new Set());
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
    if (!pendingIntent) return;
    if (pendingIntent.openGenerator) openGenerator();
    if (pendingIntent.week_start) {
      const d = new Date(pendingIntent.week_start + "T00:00:00");
      setVisibleMonth({ year: d.getFullYear(), month: d.getMonth() });
    }
    onIntentConsumed();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingIntent]);

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

  // Builds the list and leaves it on screen inside the open modal — closing is
  // the user's call (they may want to tweak the range and regenerate).
  async function generateShoppingForRange(start: string, end: string) {
    setShoppingBusy(true);
    setError("");
    try {
      setShopping(await mealsShoppingList(start, end));
      // Restore any items already ticked off for this exact date range.
      try {
        const all = JSON.parse(localStorage.getItem(SHOP_CHECKS_KEY) || "{}");
        setShopChecked(new Set<number>(all[`${start}_${end}`] ?? []));
      } catch {
        setShopChecked(new Set());
      }
    } catch (e) {
      setShopping(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setShoppingBusy(false);
    }
  }

  // Toggle an item's checked state and persist it per-device for this date range.
  function toggleShopChecked(fdcId: number) {
    setShopChecked((prev) => {
      const next = new Set(prev);
      if (next.has(fdcId)) next.delete(fdcId);
      else next.add(fdcId);
      try {
        const all = JSON.parse(localStorage.getItem(SHOP_CHECKS_KEY) || "{}");
        all[`${shopStart}_${shopEnd}`] = [...next];
        localStorage.setItem(SHOP_CHECKS_KEY, JSON.stringify(all));
      } catch {
        /* ignore quota / serialization errors */
      }
      return next;
    });
  }

  function openShopping(start: string = TODAY_MONDAY, end: string = addDays(TODAY_MONDAY, 6)) {
    setShopStart(start);
    setShopEnd(end);
    setShopping(null);
    setError("");
    setShopOpen(true);
  }

  // Quick path: open the picker on the Mon–Sun week containing a given day and
  // build that week straight away.
  function generateShoppingForWeekOf(dateIso: string) {
    const monday = mondayOf(dateIso);
    const sunday = addDays(monday, 6);
    openShopping(monday, sunday);
    return generateShoppingForRange(monday, sunday);
  }

  const shopDays = useMemo(() => {
    const ms = new Date(shopEnd + "T00:00:00").getTime()
             - new Date(shopStart + "T00:00:00").getTime();
    if (Number.isNaN(ms) || ms < 0) return 0;
    return Math.floor(ms / 86_400_000) + 1;
  }, [shopStart, shopEnd]);

  const shopItemCount = shopping
    ? shopping.categories.reduce((n, c) => n + c.items.length, 0)
    : 0;

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
    ? t("mealplan.errors.endBeforeStart")
    : genDays > 14
    ? t("mealplan.errors.tooManyDays")
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
    setReviewPlan(null);
    setFlaggedIds(new Set());
    setSoloDays(new Set());
    setError("");
    setGenOpen(true);
  }
  function toggleSoloDay(offset: number) {
    setSoloDays((prev) => {
      const next = new Set(prev);
      if (next.has(offset)) next.delete(offset); else next.add(offset);
      return next;
    });
  }
  function closeGenerator() { if (!generating) setGenOpen(false); }

  // Pre-flight: before generating, check the chosen range for days already
  // planned. If any exist, route to the keep/replace step; otherwise generate
  // straight away. Default is KEEP everything (never double-book).
  async function prepareGenerate() {
    if (Array.from(enabledSlots).length === 0) { setError(t("mealplan.errors.pickSlot")); return; }
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
    if (slot_configs.length === 0) { setError(t("mealplan.errors.pickSlot")); return; }
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
          solo_day_offsets: Array.from(soloDays).filter((d) => d >= 0 && d < genDays),
          locale: i18n.language,
        },
        (event) => {
          const item = buildFeedItem(t, event);
          if (!item) return;
          // Upsert by id: a terminal event (recipe_done / planning_done / complete)
          // replaces its matching pending row in place so the spinner flips to a
          // check rather than leaving a stale "Generating…" line behind.
          setFeed((prev) => {
            const idx = prev.findIndex((f) => f.id === item.id);
            if (idx === -1) return [...prev, item];
            const next = prev.slice();
            next[idx] = item;
            return next;
          });
        },
      );
      // Jump the calendar to the month containing the generated plan, then move
      // to the review step so the user can flag days to re-roll before finishing.
      const startD = new Date(plan.start_date + "T00:00:00");
      setVisibleMonth({ year: startD.getFullYear(), month: startD.getMonth() });
      fetchRecipes().then(setRecipes).catch(() => {});
      setReviewPlan(plan);
      setFlaggedIds(new Set());
      setGenStep(3);
    } catch (e) {
      setError(String(e));
    } finally {
      clearInterval(timer);
      setGenerating(false);
    }
  }

  function toggleFlag(entryId: string) {
    setFlaggedIds((prev) => {
      const next = new Set(prev);
      if (next.has(entryId)) next.delete(entryId); else next.add(entryId);
      return next;
    });
  }

  async function regenerateFlagged() {
    if (!reviewPlan || flaggedIds.size === 0 || regenerating) return;
    setRegenerating(true); setError("");
    try {
      const updated = await regenerateMealPlan(
        reviewPlan.id, Array.from(flaggedIds), genPrompt.trim(), genServings, i18n.language,
      );
      setReviewPlan(updated);
      setFlaggedIds(new Set());
      fetchRecipes().then(setRecipes).catch(() => {});
      void reloadMeals(gridStart, gridEnd);
    } catch (e) {
      setError(String(e));
    } finally {
      setRegenerating(false);
    }
  }

  function finishReview() {
    setGenOpen(false);
    setGenPrompt("");
    setReviewPlan(null);
    setFlaggedIds(new Set());
    void reloadMeals(gridStart, gridEnd);
  }

  // =================================================================
  // Render
  // =================================================================

  return (
    <div className="col gap-4">
      <ErrorBanner>{error}</ErrorBanner>

      <div className="plan-toolbar">
        <div className="row gap-1 items-center">
          <IconButton onClick={() => jumpMonth(-1)} title={t("mealplan.toolbar.prevMonth")} aria-label={t("mealplan.toolbar.prevMonth")}>
            <ChevronLeft size={18} />
          </IconButton>
          <div className="plan-toolbar-week">
            <span className="fw-600">{monthHeading}</span>
            {isCurrentMonth && <span className="tiny muted ml-1">{t("mealplan.toolbar.thisMonth")}</span>}
          </div>
          <IconButton onClick={() => jumpMonth(1)} title={t("mealplan.toolbar.nextMonth")} aria-label={t("mealplan.toolbar.nextMonth")}>
            <ChevronRight size={18} />
          </IconButton>
          {!isCurrentMonth && (
            <Button onClick={goToToday} variant="ghost" size="sm" className="ml-2">{t("mealplan.toolbar.today")}</Button>
          )}
          {busy && <span className="tiny muted ml-2">{t("common.loading")}</span>}
        </div>

        <div className="row gap-2 ml-auto">
          <Button onClick={openGenerator} variant="accent" size="sm">
            <Sparkles size={14} /> {t("mealplan.toolbar.generateWithAi")}
          </Button>
          <Button
            onClick={() => openShopping()}
            disabled={shoppingBusy}
            variant="primary"
            size="sm"
          >
            <ShoppingCart size={14} /> {shoppingBusy ? t("mealplan.toolbar.building") : t("mealplan.toolbar.shoppingList")}
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
                      {new Date(date + "T00:00:00").toLocaleDateString(i18n.language, { month: "short" })}
                    </span>
                  )}
                </div>
                {dinner ? (
                  <div className={"month-cell-card" + (dinner.source_entry_id ? " month-cell-card-bag" : "")}>
                    <div className="month-cell-card-name">{dinner.recipe_name}</div>
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
                    {dinner.source_entry_id ? (
                      <div className="cell-tag cell-tag-bag"><Sandwich size={11} /> {t("mealplan.cell.lunchBag")}</div>
                    ) : dinner.lunch_bags > 0 ? (
                      <div className="cell-tag"><ChefHat size={11} /> {t("mealplan.cell.cookBags", { count: dinner.lunch_bags })}</div>
                    ) : null}
                    {cellMeals.length > 1 && (
                      <div className="month-cell-more">{t("mealplan.cell.more", { count: cellMeals.length - 1 })}</div>
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
                  onClick={() => { const d = selectedDay; setSelectedDay(null); generateShoppingForWeekOf(d); }}
                  variant="ghost"
                  size="sm"
                >
                  <ShoppingCart size={12} /> {t("mealplan.day.weekShopping")}
                </Button>
              </div>
              <div className="col gap-2 mt-3">
                {dayMeals.map((m) => (
                  <div key={m.id} className="cell-recipe">
                    <div className="cell-recipe-name">{m.recipe_name}</div>
                    {m.source_entry_id ? (
                      <div className="cell-tag cell-tag-bag"><Sandwich size={11} /> {t("mealplan.day.lunchBagFromCook")}</div>
                    ) : m.lunch_bags > 0 ? (
                      <div className="cell-tag"><ChefHat size={11} /> {t("mealplan.day.cookedHere", { count: m.lunch_bags })}</div>
                    ) : null}
                    <div className="cell-recipe-meta">
                      <Input
                        type="number" min={1} value={m.portions}
                        onChange={(ev) => changePortions(m.id, Number(ev.target.value) || 1)}
                        className="input-mini"
                      />
                      <span className="tiny muted">{t("mealplan.day.portions")}</span>
                      <Button
                        onClick={() => navigateTo({ tab: "recipe", recipe_id: m.recipe_id })}
                        variant="ghost"
                        size="xs"
                        className="ml-auto"
                      >
                        <BookOpen size={12} /> {t("mealplan.day.viewRecipe")}
                      </Button>
                      <IconButton
                        onClick={() => removeMeal(m.id)}
                        className="icon-btn-sm"
                        aria-label={t("common.remove")}
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
                  <Plus size={12} /> {t("mealplan.day.addAnotherDinner")}
                </button>
              </div>
            </>
          );
        })()}
      </Modal>

      {genOpen && (
        <div className="plan-shell" role="dialog" aria-modal>
          <div className="brand auth-brand plan-shell-brand">
            <span className="brand-mark">{t("mealplan.wizard.brandMark")}</span>
            <span className="brand-tag">{t("mealplan.wizard.brandTag")}</span>
          </div>

          <Card className="plan-shell-card">
            <div className="tour-dots" aria-hidden>
              {[0, 1].map((i) => (
                <span key={i} className={"tour-dot" + (i === Math.min(genStep, 1) ? " tour-dot-active" : "")} />
              ))}
            </div>

            {genStep === 0 && (
              <div className="col-2">
                <h2 className="m-0">{t("mealplan.wizard.basicsHeading")}</h2>
                <p className="muted m-0">
                  {t("mealplan.wizard.basicsIntro")}
                </p>
                <Field>
                  {t("mealplan.wizard.cookingForHowMany")}
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
                  {t("mealplan.wizard.rangeSummary", { range: `${formatDay(genStart)} → ${formatDay(genEnd)}`, count: genDays })}
                </p>
                {genDays > 0 && (
                  <div className="col-2 items-start">
                    <span className="fw-500">{t("mealplan.wizard.soloHeading")}</span>
                    <p className="tiny muted m-0">
                      {t("mealplan.wizard.soloIntro")}
                    </p>
                    <div className="row gap-2 wrap mt-1">
                      {Array.from({ length: genDays }, (_, off) => {
                        const d = addDays(genStart, off);
                        return (
                          <Chip
                            key={off}
                            active={soloDays.has(off)}
                            onClick={() => toggleSoloDay(off)}
                          >
                            {new Date(d + "T00:00:00").toLocaleDateString(i18n.language, { weekday: "short", day: "numeric" })}
                          </Chip>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}

            {genStep === 1 && (
              <div className="col-2">
                <h2 className="m-0">{t("mealplan.wizard.briefHeading")}</h2>
                <p className="muted m-0">
                  <Trans i18nKey="mealplan.wizard.briefIntro"><em>this</em></Trans>
                </p>
                <ProfileContextCard profile={profile} />
                <Field className="field-col">
                  <Textarea
                    placeholder={t("mealplan.wizard.briefPlaceholder")}
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
                <h2 className="m-0">{t("mealplan.wizard.conflictsHeading")}</h2>
                <p className="muted m-0">
                  <Trans i18nKey="mealplan.wizard.conflictsIntro"><em>Replace</em></Trans>
                </p>
                <div className="row gap-2 items-center">
                  <span className="tiny muted flex-1">
                    {t("mealplan.wizard.plannedDays", { count: conflicts.length })}
                  </span>
                  <Button
                    size="xs"
                    variant={replaceIds.size === 0 ? "primary" : "ghost"}
                    onClick={keepAll}
                    disabled={generating}
                  >
                    {t("mealplan.wizard.keepAll")}
                  </Button>
                  <Button
                    size="xs"
                    variant={replaceIds.size === conflicts.length ? "primary" : "ghost"}
                    onClick={replaceAll}
                    disabled={generating}
                  >
                    {t("mealplan.wizard.replaceAll")}
                  </Button>
                </div>
                <div className="col gap-2">
                  {conflicts.map((c) => {
                    const replace = replaceIds.has(c.entry_id);
                    return (
                      <div key={c.entry_id} className="row gap-2 items-center pick-row">
                        <div className="flex-1">
                          <div className="fw-500">{formatDay(c.plan_date)} · {el.slot(c.slot)}</div>
                          <div className="tiny muted">{c.recipe_name ?? t("mealplan.wizard.plannedMeal")}</div>
                        </div>
                        <Button
                          size="xs"
                          variant={replace ? "ghost" : "primary"}
                          onClick={() => toggleReplace(c.entry_id, false)}
                          disabled={generating}
                        >
                          {t("mealplan.wizard.keep")}
                        </Button>
                        <Button
                          size="xs"
                          variant={replace ? "primary" : "ghost"}
                          onClick={() => toggleReplace(c.entry_id, true)}
                          disabled={generating}
                        >
                          {t("mealplan.wizard.replace")}
                        </Button>
                      </div>
                    );
                  })}
                </div>
                <p className="tiny muted m-0">
                  {replaceIds.size === 0
                    ? t("mealplan.wizard.keepingAll")
                    : t("mealplan.wizard.replacingSome", { replaced: replaceIds.size, total: conflicts.length })}
                </p>
              </div>
            )}

            {genStep === 3 && reviewPlan && (
              <div className="col-2">
                <h2 className="m-0">{t("mealplan.wizard.reviewHeading")}</h2>
                <p className="muted m-0">
                  {t("mealplan.wizard.reviewIntro")}
                </p>
                <div className="col gap-2">
                  {[...reviewPlan.entries]
                    .sort((a, b) =>
                      (a.plan_date + (a.slot ?? "")).localeCompare(b.plan_date + (b.slot ?? "")))
                    .map((e) => {
                      const flagged = flaggedIds.has(e.id);
                      return (
                        <div key={e.id} className="row gap-2 items-center pick-row">
                          <div className="flex-1">
                            <div className="fw-500">
                              {formatDay(e.plan_date)}{e.slot ? ` · ${el.slot(e.slot)}` : ""}
                            </div>
                            <div className="tiny muted">{e.recipe_name ?? t("mealplan.wizard.plannedMeal")}</div>
                            {e.source_entry_id ? (
                              <div className="cell-tag cell-tag-bag"><Sandwich size={11} /> {t("mealplan.cell.lunchBag")}</div>
                            ) : e.lunch_bags > 0 ? (
                              <div className="cell-tag"><ChefHat size={11} /> {t("mealplan.wizard.reviewCookBags", { count: e.lunch_bags })}</div>
                            ) : null}
                          </div>
                          <Button
                            size="xs"
                            variant={flagged ? "primary" : "ghost"}
                            onClick={() => toggleFlag(e.id)}
                            disabled={regenerating}
                          >
                            {flagged ? t("mealplan.wizard.willRedo") : t("mealplan.wizard.redo")}
                          </Button>
                        </div>
                      );
                    })}
                </div>
                <p className="tiny muted m-0">
                  {flaggedIds.size === 0
                    ? t("mealplan.wizard.nothingFlagged")
                    : t("mealplan.wizard.redoingDays", { count: flaggedIds.size })}
                </p>
                {regenerating && (
                  <div className="row gap-2 items-center">
                    <div className="chat-typing"><span></span><span></span><span></span></div>
                    <span className="tiny muted">{t("mealplan.wizard.cookingReplacements")}</span>
                  </div>
                )}
              </div>
            )}

            <div className="row gap-2 mt-4">
              {genStep === 3 ? (
                <>
                  <Button
                    variant="ghost"
                    onClick={regenerateFlagged}
                    disabled={regenerating || flaggedIds.size === 0}
                  >
                    {regenerating
                      ? t("mealplan.wizard.regenerating")
                      : flaggedIds.size > 0
                      ? t("mealplan.wizard.regenerateCount", { count: flaggedIds.size })
                      : t("mealplan.wizard.regenerateFlagged")}
                  </Button>
                  <Button
                    variant="primary"
                    onClick={finishReview}
                    disabled={regenerating}
                    className="flex-1"
                  >
                    {t("mealplan.wizard.looksGood")}
                  </Button>
                </>
              ) : (
                <>
                  {genStep > 0 ? (
                    <Button
                      variant="ghost"
                      onClick={() => setGenStep(genStep === 2 ? 1 : 0)}
                      disabled={generating || checkingConflicts}
                    >
                      {t("common.back")}
                    </Button>
                  ) : (
                    <Button variant="ghost" onClick={closeGenerator} disabled={generating}>
                      {t("common.cancel")}
                    </Button>
                  )}
                  {genStep === 0 && (
                    <Button
                      variant="primary"
                      onClick={() => setGenStep(1)}
                      disabled={generating || genRangeError !== null}
                      className="flex-1"
                    >
                      {t("mealplan.wizard.continue")}
                    </Button>
                  )}
                  {genStep === 1 && (
                    <Button
                      variant="accent"
                      onClick={prepareGenerate}
                      disabled={generating || checkingConflicts}
                      className="flex-1"
                    >
                      {checkingConflicts ? t("mealplan.wizard.checkingCalendar") : t("mealplan.wizard.generatePlan")}
                    </Button>
                  )}
                  {genStep === 2 && (
                    <Button
                      variant="accent"
                      onClick={() => runWeeklyGenerator(Array.from(replaceIds))}
                      disabled={generating}
                      className="flex-1"
                    >
                      {generating ? t("mealplan.wizard.draftingYourWeek") : t("mealplan.wizard.generatePlan")}
                    </Button>
                  )}
                </>
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
                      {generating ? t("mealplan.wizard.feedDraftingTitle") : t("mealplan.wizard.feedStoppedTitle")}
                    </div>
                    <div className="tiny muted">
                      {generating ? t("mealplan.wizard.feedElapsed", { seconds: genElapsed }) : t("mealplan.wizard.feedLastRun", { seconds: genElapsed })}
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
              <h3>{t("mealplan.picker.heading")}</h3>
              <p className="small muted">
                {formatDay(pickerCell.date)} · <span className="capitalize">{el.slot(slot)}</span>
              </p>
              <Input
                placeholder={t("mealplan.picker.searchPlaceholder", { count: recipes.length })}
                value={pickerQuery}
                onChange={(e) => setPickerQuery(e.target.value)}
                autoFocus
                className="mt-2"
              />
              {recipes.length === 0 && <Empty>{t("mealplan.picker.noSavedRecipes")}</Empty>}
              {recipes.length > 0 && sorted.length === 0 && (
                <Empty>{t("mealplan.picker.noMatches", { query: pickerQuery })}</Empty>
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
                            {el.slot(r.meal_type)}
                          </Pill>
                        )}
                      </div>
                      <div className="tiny muted">
                        {t("mealplan.picker.servingsToBuy", { servings: r.servings, toBuy: r.ingredients.length })}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <Button onClick={() => { setPickerCell(null); setPickerQuery(""); }} variant="ghost" className="mt-3">
                {t("common.cancel")}
              </Button>
            </>
          );
        })()}
      </Modal>

      {/* Shopping-list range picker + result — pick the days, then consolidate
          the meals already on the calendar for them (no AI, no credits). The
          list renders right here in the modal so it can't be missed. */}
      <Modal open={shopOpen} onClose={() => setShopOpen(false)}>
        <div className="col gap-3">
          <div>
            <h3 className="m-0">{t("mealplan.shopping.heading")}</h3>
            <span className="small muted">
              {t("mealplan.shopping.intro")}
            </span>
          </div>
          <ErrorBanner>{error}</ErrorBanner>
          <DateRangePicker
            start={shopStart}
            end={shopEnd}
            onChange={(s, e) => { setShopStart(s); setShopEnd(e); }}
            maxDays={31}
          />
          <p className="small muted m-0 text-center">
            {t("mealplan.wizard.rangeSummary", { range: `${formatDay(shopStart)} → ${formatDay(shopEnd)}`, count: shopDays })}
          </p>
          <div className="row gap-2 ml-auto">
            <Button variant="ghost" size="sm" onClick={() => setShopOpen(false)}>{t("common.close")}</Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => generateShoppingForRange(shopStart, shopEnd)}
              disabled={shoppingBusy || shopDays === 0}
            >
              <ShoppingCart size={14} />{" "}
              {shoppingBusy ? t("mealplan.toolbar.building") : shopping ? t("mealplan.shopping.regenerate") : t("mealplan.shopping.generate")}
            </Button>
          </div>

          {shopping && (
            <div className="col gap-2 mt-1">
              <div className="row between items-baseline">
                <h4 className="m-0">{t("mealplan.shopping.yourList")}</h4>
                <Pill>{t("mealplan.shopping.itemCount", { count: shopItemCount })}</Pill>
              </div>
              {shopping.categories.length === 0 && (
                <Empty>{t("mealplan.shopping.noItems")}</Empty>
              )}
              {shopping.categories.map((cat) => (
                <div key={cat.category} className="mb-2">
                  <div className="shop-cat-header">
                    <span>{el.category(cat.category)}</span>
                    <span className="shop-cat-count">{cat.items.length}</span>
                  </div>
                  {cat.items.map((item) => {
                    const isChecked = shopChecked.has(item.fdc_id);
                    return (
                      <label key={item.fdc_id} className={`shop-row ${isChecked ? "checked" : ""}`}>
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={() => toggleShopChecked(item.fdc_id)}
                        />
                        <span className="flex-1">{el.ingredient(item.fdc_id, item.name)}</span>
                        <span className={`shop-qty ${isChecked ? "checked" : ""}`}>{item.display_quantity} {el.unit(item.display_unit)}</span>
                        {item.display_unit !== "g" && (
                          <span className="tiny muted">{t("mealplan.shopping.approxGrams", { grams: Math.round(item.quantity_g) })}</span>
                        )}
                      </label>
                    );
                  })}
                </div>
              ))}
            </div>
          )}
        </div>
      </Modal>
    </div>
  );
}


function buildFeedItem(t: import("i18next").TFunction, event: GenerateEvent): {
  id: string;
  status: "pending" | "done" | "failed";
  icon: ReactNode;
  text: string;
} | null {
  // Stable ids so a start event and its matching terminal event collapse onto
  // one line (the spinner flips to a check) instead of leaving a dangling
  // "Generating…" row. Recipe events are keyed by their backend index.
  const rnd = () => `${event.type}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  switch (event.type) {
    case "planning_start":
      return { id: "planning", status: "pending", icon: <Sparkles size={14} />,
        text: t("mealplan.feed.draftingWeek", { count: event.days, slots: event.slots.join(" + ") }) };
    case "planning_done":
      return { id: "planning", status: "done", icon: <Check size={14} />,
        text: t("mealplan.feed.drafted", { name: event.plan_name, meals: event.meals_proposed, recipes: event.recipes_to_generate }) };
    case "recipe_start":
      return { id: `recipe-${event.index}`, status: "pending", icon: <Sparkles size={14} />,
        text: event.reason
          ? t("mealplan.feed.generatingRecipeReason", { prompt: event.prompt, reason: event.reason })
          : t("mealplan.feed.generatingRecipe", { prompt: event.prompt }) };
    case "recipe_done":
      return { id: `recipe-${event.index}`, status: "done", icon: <Check size={14} />, text: t("mealplan.feed.madeRecipe", { name: event.name, duration: event.duration }) };
    case "recipe_failed":
      return { id: `recipe-${event.index}`, status: "failed", icon: <X size={14} />, text: t("mealplan.feed.recipeFailed", { prompt: event.prompt, error: event.error }) };
    case "persisting":
      return { id: "finalize", status: "pending", icon: <Save size={14} />, text: t("mealplan.feed.saving") };
    case "complete":
      return { id: "finalize", status: "done", icon: <Check size={14} />, text: t("mealplan.feed.complete", { duration: event.total_duration }) };
    case "error":
      return { id: rnd(), status: "failed", icon: <X size={14} />, text: event.message };
  }
}


function ProfileContextCard({ profile }: { profile: ProfileSummary | null }) {
  const { t } = useTranslation();
  if (!profile) {
    return <Card variant="soft" className="mt-2"><p className="small muted m-0">{t("mealplan.profileCard.loading")}</p></Card>;
  }
  const chips: string[] = [];
  if (profile.family_size && profile.family_size > 0) chips.push(t("mealplan.profileCard.cookingFor", { count: profile.family_size }));
  profile.dietary.forEach((d) => chips.push(d));
  if (profile.allergies.length > 0) chips.push(t("mealplan.profileCard.noAllergies", { list: profile.allergies.join(", ") }));
  if (profile.typical_cook_time_min) chips.push(t("mealplan.profileCard.cookTime", { minutes: profile.typical_cook_time_min }));
  profile.cuisines.slice(0, 4).forEach((c) => chips.push(c));
  if (profile.batch_cook_preference && profile.batch_cook_preference !== "none") {
    chips.push(t("mealplan.profileCard.batchCook", { preference: profile.batch_cook_preference }));
  }
  if (chips.length === 0) {
    return (
      <Card variant="soft" className="mt-2">
        <p className="small m-0">{t("mealplan.profileCard.emptyTitle")}</p>
        <p className="tiny muted m-0 mt-1">
          {t("mealplan.profileCard.emptyHint")}
        </p>
      </Card>
    );
  }
  return (
    <Card variant="soft" className="mt-2">
      <p className="tiny muted m-0">{t("mealplan.profileCard.learnedTitle")}</p>
      <div className="row wrap gap-2 mt-2">
        {chips.map((c, i) => (<Pill key={i}>{c}</Pill>))}
      </div>
      <p className="tiny muted m-0 mt-2">
        {t("mealplan.profileCard.wrongOrMissing")}
      </p>
    </Card>
  );
}
