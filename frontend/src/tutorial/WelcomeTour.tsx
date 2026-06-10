/**
 * First-run welcome tour — explains Mealplanner's loop in three short screens.
 *
 * Shown once per browser (gated by localStorage). Skippable at any step.
 * Re-triggerable via the "Replay tour" button on the Household tab.
 *
 * Trigger lives in App.tsx — this component is purely presentational.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { CalendarRange, ChefHat, ShoppingCart } from "lucide-react";
import { Button, Card } from "../components/ui";

interface Props {
  open: boolean;
  onClose: () => void;
}

const STORAGE_KEY = "hearth.welcome_seen";

const STEPS = [
  {
    icon: CalendarRange,
    titleKey: "tour.steps.plan.title",
    bodyKey: "tour.steps.plan.body",
  },
  {
    icon: ChefHat,
    titleKey: "tour.steps.cook.title",
    bodyKey: "tour.steps.cook.body",
  },
  {
    icon: ShoppingCart,
    titleKey: "tour.steps.shop.title",
    bodyKey: "tour.steps.shop.body",
  },
] as const;

export default function WelcomeTour({ open, onClose }: Props) {
  const { t } = useTranslation();
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
        <span className="brand-mark">Mealplanner</span>
        <span className="brand-tag">{t("tour.brandTag")}</span>
      </div>

      <Card className="auth-card tour-card">
        <div className="tour-icon"><Icon size={36} /></div>
        <h2 className="text-center">{t(current.titleKey)}</h2>
        <p className="muted text-center">{t(current.bodyKey)}</p>

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
            <Button variant="ghost" onClick={back}>{t("common.back")}</Button>
          )}
          <Button variant="primary" block onClick={next}>
            {isLast ? t("tour.getStarted") : t("common.next")}
          </Button>
        </div>

        <button type="button" className="link-button mt-3" onClick={dismiss}>
          {t("tour.skipTour")}
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
