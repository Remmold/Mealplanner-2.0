import { useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { Button, Card, Chip, ErrorBanner, Field, Input } from "../components/ui";
import { patchProfile } from "../lib/auth-api";
import type { ProfilePatch } from "../lib/auth-api";

const DIETARY = [
  "vegetarian", "vegan", "pescatarian", "gluten-free",
  "dairy-free", "nut-free", "halal", "kosher",
] as const;

const CUISINES = [
  "Italian", "Thai", "Mexican", "Indian", "Japanese", "Mediterranean",
  "Chinese", "American", "French", "Middle Eastern", "Korean", "Greek",
  "Swedish", "Vietnamese",
] as const;

interface WizardData {
  family_size: number | null;
  dietary: string[];
  allergies: string[];
  cuisines: string[];
  typical_cook_time_min: number | null;
}

const EMPTY: WizardData = {
  family_size: null,
  dietary: [],
  allergies: [],
  cuisines: [],
  typical_cook_time_min: null,
};

const STEPS = 5;
const STORAGE_KEY = "hearth.wizard_done";

interface Props {
  onComplete: () => void;
}

export default function ProfileWizard({ onComplete }: Props) {
  const [step, setStep] = useState(0);
  const [data, setData] = useState<WizardData>(EMPTY);
  const [allergyInput, setAllergyInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function next() {
    setStep((s) => Math.min(s + 1, STEPS - 1));
  }

  function back() {
    setStep((s) => Math.max(s - 1, 0));
  }

  function toggle(field: "dietary" | "cuisines", item: string) {
    setData((d) => {
      const cur = d[field];
      return {
        ...d,
        [field]: cur.includes(item) ? cur.filter((x) => x !== item) : [...cur, item],
      };
    });
  }

  function addAllergy() {
    const t = allergyInput.trim();
    if (!t || data.allergies.includes(t)) return;
    setData((d) => ({ ...d, allergies: [...d.allergies, t] }));
    setAllergyInput("");
  }

  function onAllergyKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addAllergy();
    }
  }

  function removeAllergy(item: string) {
    setData((d) => ({ ...d, allergies: d.allergies.filter((x) => x !== item) }));
  }

  async function finish(skipped: boolean) {
    setError(null);

    if (!skipped) {
      const patch: ProfilePatch = {};
      if (data.family_size !== null) patch.family_size = data.family_size;
      if (data.dietary.length > 0) patch.dietary = data.dietary;
      if (data.allergies.length > 0) patch.allergies = data.allergies;
      if (data.cuisines.length > 0) patch.cuisines = data.cuisines;
      if (data.typical_cook_time_min !== null)
        patch.typical_cook_time_min = data.typical_cook_time_min;

      if (Object.keys(patch).length > 0) {
        setBusy(true);
        try {
          await patchProfile(patch);
        } catch (e) {
          setError(e instanceof Error ? e.message : String(e));
          setBusy(false);
          return;
        }
        setBusy(false);
      }
    }

    try { localStorage.setItem(STORAGE_KEY, "1"); } catch { /* ignore */ }
    onComplete();
  }

  return (
    <div className="auth-shell">
      <div className="brand auth-brand">
        <span className="brand-mark">Hearth</span>
        <span className="brand-tag">tell us about your kitchen</span>
      </div>

      <Card className="auth-card">
        {error && <ErrorBanner>{error}</ErrorBanner>}

        <div className="muted text-center">
          Step {step + 1} of {STEPS}
        </div>

        {step === 0 && (
          <Step
            title="How many people do you cook for?"
            sub="Plans and shopping lists scale to this number."
          >
            <Field>
              <Input
                type="number"
                numeric
                min={1}
                max={20}
                value={data.family_size ?? ""}
                onChange={(e) =>
                  setData((d) => ({
                    ...d,
                    family_size: e.target.value ? Number(e.target.value) : null,
                  }))
                }
                placeholder="e.g. 2"
                autoFocus
              />
            </Field>
          </Step>
        )}

        {step === 1 && (
          <Step
            title="Any dietary preferences?"
            sub="Pick what applies. We'll respect these in suggestions."
          >
            <div className="chip-grid">
              {DIETARY.map((d) => (
                <Chip
                  key={d}
                  active={data.dietary.includes(d)}
                  onClick={() => toggle("dietary", d)}
                >
                  {d}
                </Chip>
              ))}
            </div>
          </Step>
        )}

        {step === 2 && (
          <Step
            title="Any allergies?"
            sub="Strict avoidances — we'll never include these in a recipe."
          >
            <Field>
              <Input
                type="text"
                value={allergyInput}
                onChange={(e) => setAllergyInput(e.target.value)}
                onKeyDown={onAllergyKey}
                placeholder="Type and press Enter (e.g. peanuts)"
                autoFocus
              />
            </Field>
            {data.allergies.length > 0 && (
              <div className="chip-grid mt-3">
                {data.allergies.map((a) => (
                  <Chip key={a} active onRemove={() => removeAllergy(a)}>{a}</Chip>
                ))}
              </div>
            )}
          </Step>
        )}

        {step === 3 && (
          <Step
            title="Favourite cuisines?"
            sub="We'll lean into these when generating ideas."
          >
            <div className="chip-grid">
              {CUISINES.map((c) => (
                <Chip
                  key={c}
                  active={data.cuisines.includes(c)}
                  onClick={() => toggle("cuisines", c)}
                >
                  {c}
                </Chip>
              ))}
            </div>
          </Step>
        )}

        {step === 4 && (
          <Step
            title="How long can you cook on a weeknight?"
            sub="Minutes from start to plate."
          >
            <Field>
              <Input
                type="number"
                numeric
                min={10}
                max={180}
                value={data.typical_cook_time_min ?? ""}
                onChange={(e) =>
                  setData((d) => ({
                    ...d,
                    typical_cook_time_min: e.target.value
                      ? Number(e.target.value)
                      : null,
                  }))
                }
                placeholder="e.g. 30"
                autoFocus
              />
            </Field>
          </Step>
        )}

        <div className="auth-actions mt-4">
          {step > 0 && (
            <Button variant="ghost" onClick={back} disabled={busy}>
              Back
            </Button>
          )}
          {step < STEPS - 1 ? (
            <>
              <Button variant="ghost" onClick={next} disabled={busy}>
                Skip
              </Button>
              <Button variant="primary" onClick={next} disabled={busy} className="flex-1">
                Continue <ChevronRight size={14} />
              </Button>
            </>
          ) : (
            <Button
              variant="primary"
              onClick={() => finish(false)}
              disabled={busy}
              className="flex-1"
            >
              {busy ? "Saving..." : "Save & finish"}
            </Button>
          )}
        </div>

        <button
          type="button"
          className="link-button mt-3"
          onClick={() => finish(true)}
          disabled={busy}
        >
          Skip all &mdash; set up later
        </button>
      </Card>
    </div>
  );
}

function Step({
  title,
  sub,
  children,
}: {
  title: string;
  sub: string;
  children: ReactNode;
}) {
  return (
    <div>
      <h2>{title}</h2>
      <p className="muted">{sub}</p>
      <div className="mt-4">{children}</div>
    </div>
  );
}

export function wizardWasDismissed(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}
