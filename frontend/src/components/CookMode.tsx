/**
 * Full-screen step-by-step cooking view.
 *
 * Features:
 * - One step on screen at a time, big readable type.
 * - Auto-detects "X minutes" / "X-Y minutes" in the step text and offers a
 *   one-tap timer that beeps on completion.
 * - Ingredient list as a slide-up sheet, quantities scaled to "cooking for N"
 *   (which can differ from the recipe's base servings without saving).
 * - Per-step "done" tracking. Closing CookMode resets state.
 *
 * Used from RecipeBuilder via the "Start cooking" button.
 */

import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Check, ChevronLeft, ChevronRight, ListOrdered, Play, RotateCcw, X } from "lucide-react";
import type { Recipe } from "../api";
import { useEnumLabels } from "../i18n/enums";
import { Button, Card, IconButton } from "./ui";


interface Props {
  open: boolean;
  recipe: Recipe;
  onClose: () => void;
}


export default function CookMode({ open, recipe, onClose }: Props) {
  const { t } = useTranslation();

  const [stepIdx, setStepIdx] = useState(0);
  const [doneSteps, setDoneSteps] = useState<Set<number>>(new Set());
  const [showIngredients, setShowIngredients] = useState(false);
  const [timerTotal, setTimerTotal] = useState<number | null>(null);
  const [timerRemaining, setTimerRemaining] = useState<number>(0);
  const [timerActive, setTimerActive] = useState(false);
  const beepedRef = useRef(false);

  // Reset everything when the modal closes / a different recipe is loaded
  useEffect(() => {
    if (!open) {
      setStepIdx(0);
      setDoneSteps(new Set());
      setShowIngredients(false);
      setTimerTotal(null);
      setTimerRemaining(0);
      setTimerActive(false);
      beepedRef.current = false;
    }
  }, [open]);

  // Tick the timer once per second while active
  useEffect(() => {
    if (!timerActive || timerRemaining <= 0) return;
    const id = setInterval(() => {
      setTimerRemaining((r) => Math.max(0, r - 1));
    }, 1000);
    return () => clearInterval(id);
  }, [timerActive, timerRemaining]);

  // Beep + stop when timer hits zero
  useEffect(() => {
    if (timerActive && timerRemaining === 0 && !beepedRef.current) {
      beepedRef.current = true;
      setTimerActive(false);
      playBeep();
    }
  }, [timerActive, timerRemaining]);

  if (!open) return null;

  const steps = recipe.instructions ?? [];
  const totalSteps = steps.length;
  const currentStep = steps[stepIdx] ?? "";
  const stepTimerSecs = parseStepMinutes(currentStep);
  const isFirst = stepIdx === 0;
  const isLast = stepIdx === Math.max(0, totalSteps - 1);
  const isDone = doneSteps.has(stepIdx);

  function startTimer(seconds: number) {
    setTimerTotal(seconds);
    setTimerRemaining(seconds);
    setTimerActive(true);
    beepedRef.current = false;
  }

  function resetTimer() {
    if (timerTotal !== null) {
      setTimerRemaining(timerTotal);
      setTimerActive(false);
      beepedRef.current = false;
    }
  }

  function clearTimer() {
    setTimerTotal(null);
    setTimerRemaining(0);
    setTimerActive(false);
    beepedRef.current = false;
  }

  function toggleDone() {
    setDoneSteps((s) => {
      const n = new Set(s);
      if (n.has(stepIdx)) n.delete(stepIdx);
      else n.add(stepIdx);
      return n;
    });
  }

  function next() {
    if (stepIdx < totalSteps - 1) {
      setStepIdx((i) => i + 1);
      clearTimer();
    }
  }

  function prev() {
    if (stepIdx > 0) {
      setStepIdx((i) => i - 1);
      clearTimer();
    }
  }

  return (
    <div className="cook-shell" role="dialog" aria-modal>
      <header className="cook-header">
        <div className="cook-header-title">
          <h2>{recipe.name}</h2>
          <p className="muted">
            {t("cook.stepProgress", { current: stepIdx + 1, total: totalSteps || 1 })}
          </p>
        </div>
        <div className="cook-header-controls">
          <IconButton onClick={onClose} title={t("cook.closeCookMode")} aria-label={t("cook.closeCookMode")}>
            <X size={22} />
          </IconButton>
        </div>
      </header>

      <div className="cook-body">
        {totalSteps === 0 ? (
          <Card variant="soft" className="cook-step-card">
            <p className="muted">{t("cook.noInstructions")}</p>
          </Card>
        ) : (
          <Card variant={isDone ? "default" : "soft"} className="cook-step-card">
            <div className="cook-step-meta">
              <span className="cook-step-num">{stepIdx + 1}</span>
              {isDone && <span className="cook-step-done"><Check size={14} /> {t("cook.stepDone")}</span>}
            </div>
            <p className="cook-step-text">{currentStep}</p>

            {stepTimerSecs !== null && (
              <TimerRow
                stepTimerSecs={stepTimerSecs}
                timerTotal={timerTotal}
                timerRemaining={timerRemaining}
                timerActive={timerActive}
                onStart={() => startTimer(stepTimerSecs)}
                onPauseResume={() => setTimerActive((a) => !a)}
                onReset={resetTimer}
                onClear={clearTimer}
              />
            )}
          </Card>
        )}
      </div>

      <div className="cook-nav">
        <Button variant="ghost" onClick={prev} disabled={isFirst}>
          <ChevronLeft size={16} />
          <span className="ml-1">{t("common.back")}</span>
        </Button>
        <Button variant={isDone ? "default" : "default"} onClick={toggleDone}>
          <Check size={14} />
          <span className="ml-1">{isDone ? t("cook.undoDone") : t("cook.markDone")}</span>
        </Button>
        <Button variant="primary" onClick={next} disabled={isLast} className="flex-1">
          <span>{t("common.next")}</span>
          <ChevronRight size={16} />
        </Button>
      </div>

      <button
        type="button"
        className="cook-ingredients-toggle"
        onClick={() => setShowIngredients(true)}
        aria-label={t("cook.showIngredients")}
      >
        <ListOrdered size={16} />
        <span className="ml-2">
          {t("cook.ingredientsWithCount", { count: (recipe.ingredients ?? []).length })}
        </span>
      </button>

      {showIngredients && (
        <IngredientSheet
          recipe={recipe}
          onClose={() => setShowIngredients(false)}
        />
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------

interface TimerRowProps {
  stepTimerSecs: number;
  timerTotal: number | null;
  timerRemaining: number;
  timerActive: boolean;
  onStart: () => void;
  onPauseResume: () => void;
  onReset: () => void;
  onClear: () => void;
}

function TimerRow({
  stepTimerSecs, timerTotal, timerRemaining, timerActive,
  onStart, onPauseResume, onReset, onClear,
}: TimerRowProps): ReactNode {
  const { t } = useTranslation();
  if (timerTotal === null) {
    return (
      <div className="cook-timer-row">
        <Button variant="accent" size="sm" onClick={onStart}>
          <Play size={14} />
          <span className="ml-1">{t("cook.startMinTimer", { minutes: Math.round(stepTimerSecs / 60) })}</span>
        </Button>
      </div>
    );
  }

  const done = timerRemaining === 0;

  return (
    <div className="cook-timer-row">
      <span className={"cook-timer-display" + (done ? " cook-timer-done" : "")}>
        {formatTimer(timerRemaining)}
      </span>
      {!done && (
        <Button variant="ghost" size="sm" onClick={onPauseResume}>
          {timerActive ? t("cook.pause") : t("cook.resume")}
        </Button>
      )}
      <Button variant="ghost" size="sm" onClick={onReset}>
        <RotateCcw size={14} />
        <span className="ml-1">{t("cook.reset")}</span>
      </Button>
      <Button variant="ghost" size="sm" onClick={onClear}>
        {t("cook.clear")}
      </Button>
    </div>
  );
}


// ---------------------------------------------------------------------------

interface IngredientSheetProps {
  recipe: Recipe;
  onClose: () => void;
}

function IngredientSheet({ recipe, onClose }: IngredientSheetProps): ReactNode {
  const { t } = useTranslation();
  const el = useEnumLabels();
  const ingredients = recipe.ingredients ?? [];
  return (
    <div className="cook-ingredients-sheet">
      <header className="cook-ingredients-header">
        <h3>{t("cook.ingredientsHeading")}</h3>
        <IconButton onClick={onClose} title={t("common.close")} aria-label={t("cook.closeIngredients")}>
          <X size={20} />
        </IconButton>
      </header>
      <ul className="cook-ingredients-list">
        {ingredients.length === 0 && <li className="muted">{t("cook.noIngredients")}</li>}
        {ingredients.map((ing, i) => (
          <li key={i}>
            <span className="cook-ing-name">
              {el.ingredient(ing.fdc_id, ing.ingredient_name ?? t("cook.fdcIdFallback", { id: ing.fdc_id }))}
            </span>
            <strong className="cook-ing-qty">
              {t("cook.grams", { amount: Math.max(1, Math.round(ing.quantity_g)) })}
            </strong>
          </li>
        ))}
      </ul>
    </div>
  );
}


// ---------------------------------------------------------------------------

function formatTimer(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/**
 * Detect "X min", "X-Y min", "X minutes", etc. and return total seconds for
 * the timer. For ranges, averages the two values.
 */
function parseStepMinutes(text: string): number | null {
  const re = /(\d+)(?:\s*[-–]\s*(\d+))?\s*(?:min|mins|minute|minutes)\b/i;
  const m = re.exec(text);
  if (!m) return null;
  const a = parseInt(m[1], 10);
  const b = m[2] ? parseInt(m[2], 10) : null;
  const minutes = b ? Math.ceil((a + b) / 2) : a;
  return minutes * 60;
}

/**
 * Short beep when the timer hits zero. Uses WebAudio so we don't ship audio
 * files. Silent if the browser blocks (no user-gesture context).
 */
function playBeep() {
  try {
    const AudioCtx = (window.AudioContext ?? (window as any).webkitAudioContext) as typeof AudioContext;
    const ctx = new AudioCtx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.3, ctx.currentTime + 0.05);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.6);
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.6);
    setTimeout(() => ctx.close(), 1000);
  } catch {
    /* audio context blocked — silent fail */
  }
}
