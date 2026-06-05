/**
 * First-run welcome tour — explains Hearth's loop in three short screens.
 *
 * Shown once per browser (gated by localStorage). Skippable at any step.
 * Re-triggerable via the "Replay tour" button on the Household tab.
 *
 * Trigger lives in App.tsx — this component is purely presentational.
 */

import { useState } from "react";
import { CalendarRange, ChefHat, ShoppingCart } from "lucide-react";
import { Button, Card } from "../components/ui";

interface Props {
  open: boolean;
  onClose: () => void;
}

const STORAGE_KEY = "hearth.welcome_seen";

interface Step {
  icon: typeof CalendarRange;
  title: string;
  body: string;
}

const STEPS: Step[] = [
  {
    icon: CalendarRange,
    title: "Plan your week",
    body:
      "Hearth turns a sentence (\"easy vegetarian week, batch-cook two dinners\") "
      + "into a full meal plan — generated, scaled, and respectful of your "
      + "household's dietary preferences.",
  },
  {
    icon: ChefHat,
    title: "Cook from real recipes",
    body:
      "Each meal lands as a real recipe — ingredients with quantities, "
      + "step-by-step instructions, USDA-backed nutrition. Tap a step to start "
      + "a timer; scale servings on the fly.",
  },
  {
    icon: ShoppingCart,
    title: "One trip, one list",
    body:
      "Your plan becomes a single shopping list: ingredients summed across "
      + "the week, converted to shopping units (eggs, dl, cloves), and ordered "
      + "by your store's aisle layout. No mental math.",
  },
];

export default function WelcomeTour({ open, onClose }: Props) {
  const [step, setStep] = useState(0);

  if (!open) return null;

  const isLast = step === STEPS.length - 1;
  const isFirst = step === 0;
  const current = STEPS[step];
  const Icon = current.icon;

  function dismiss() {
    try { localStorage.setItem(STORAGE_KEY, "1"); } catch { /* ignore */ }
    setStep(0);
    onClose();
  }

  function next() {
    if (isLast) dismiss();
    else setStep(step + 1);
  }

  function back() {
    if (!isFirst) setStep(step - 1);
  }

  return (
    <div className="auth-shell tour-shell" role="dialog" aria-modal>
      <div className="brand auth-brand">
        <span className="brand-mark">Hearth</span>
        <span className="brand-tag">your kitchen, planned</span>
      </div>

      <Card className="auth-card tour-card">
        <div className="tour-icon"><Icon size={36} /></div>
        <h2 className="text-center">{current.title}</h2>
        <p className="muted text-center">{current.body}</p>

        <div className="tour-dots" aria-hidden>
          {STEPS.map((_, i) => (
            <span
              key={i}
              className={"tour-dot" + (i === step ? " tour-dot-active" : "")}
            />
          ))}
        </div>

        <div className="auth-actions mt-3">
          {!isFirst && (
            <Button variant="ghost" onClick={back}>Back</Button>
          )}
          <Button variant="primary" block onClick={next}>
            {isLast ? "Got it — let's start" : "Next"}
          </Button>
        </div>

        <button type="button" className="link-button mt-3" onClick={dismiss}>
          Skip tour
        </button>
      </Card>
    </div>
  );
}

export function welcomeTourSeen(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

/** Reset so the tour shows again next render. Used by the "Replay tour" button. */
export function resetWelcomeTour(): void {
  try { localStorage.removeItem(STORAGE_KEY); } catch { /* ignore */ }
}
