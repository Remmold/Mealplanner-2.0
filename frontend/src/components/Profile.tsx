import { useEffect, useMemo, useState } from "react";
import { Plus, X } from "lucide-react";
import {
  fetchProfile,
  patchProfile,
  resetProfile,
  onDataChanged,
  dataChanged,
  fetchStaples,
  addStaple,
  removeStaple,
  type HouseholdProfile,
  type ProfilePatch,
  type StapleEntry,
} from "../api";
import { Button, Card, Empty, ErrorBanner, Field, IconButton, Input, Select } from "./ui";

const LIST_FIELDS: { key: keyof HouseholdProfile; label: string; placeholder: string }[] = [
  { key: "dietary", label: "Dietary", placeholder: "vegetarian, pescatarian, gluten-free" },
  { key: "allergies", label: "Allergies (strict)", placeholder: "peanuts, shellfish" },
  { key: "dislikes", label: "Dislikes", placeholder: "cilantro, liver" },
  { key: "likes", label: "Likes", placeholder: "bulgur, slow-roasted lamb" },
  { key: "cuisines", label: "Cuisines", placeholder: "Mediterranean, Thai, Scandi" },
  { key: "kitchen_equipment", label: "Kitchen equipment", placeholder: "oven, wok, pressure cooker" },
];

const BATCH_OPTIONS = ["", "none", "moderate", "heavy"];
const BUDGET_OPTIONS = ["", "thrifty", "moderate", "splurge"];

function splitCsv(s: string): string[] {
  return s.split(",").map((x) => x.trim()).filter(Boolean);
}

export default function Profile() {
  const [profile, setProfile] = useState<HouseholdProfile | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  // Editable local copy
  const [draft, setDraft] = useState<HouseholdProfile | null>(null);
  const [listDrafts, setListDrafts] = useState<Record<string, string>>({});
  const [newNote, setNewNote] = useState("");

  useEffect(() => { load(); }, []);
  useEffect(() => {
    return onDataChanged((kind) => { if (kind === "*") load(); });
  }, []);

  async function load() {
    try {
      const p = await fetchProfile();
      setProfile(p);
      setDraft(p);
      setListDrafts({
        dietary: p.dietary.join(", "),
        allergies: p.allergies.join(", "),
        dislikes: p.dislikes.join(", "),
        likes: p.likes.join(", "),
        cuisines: p.cuisines.join(", "),
        kitchen_equipment: p.kitchen_equipment.join(", "),
      });
      setDirty(false);
    } catch (e) { setError(String(e)); }
  }

  function updateDraft<K extends keyof HouseholdProfile>(key: K, value: HouseholdProfile[K]) {
    setDraft((d) => d ? { ...d, [key]: value } : d);
    setDirty(true);
  }

  function updateListDraft(key: string, value: string) {
    setListDrafts((prev) => ({ ...prev, [key]: value }));
    setDirty(true);
  }

  async function save() {
    if (!draft) return;
    setSaving(true); setError("");
    try {
      const patch: ProfilePatch = {
        family_size: draft.family_size,
        typical_cook_time_min: draft.typical_cook_time_min,
        batch_cook_preference: draft.batch_cook_preference || null,
        budget_level: draft.budget_level || null,
        visible_slots: draft.visible_slots ?? [],
        max_ingredients_to_buy: draft.max_ingredients_to_buy,
      };
      for (const f of LIST_FIELDS) {
        patch[f.key as keyof ProfilePatch] = splitCsv(listDrafts[f.key] ?? "") as never;
      }
      const updated = await patchProfile(patch);
      setProfile(updated);
      setDraft(updated);
      setDirty(false);
      dataChanged("*");
    } catch (e) { setError(String(e)); }
    finally { setSaving(false); }
  }

  async function addNote() {
    const note = newNote.trim();
    if (!note) return;
    try {
      const updated = await patchProfile({ append_notes: [note] });
      setProfile(updated);
      setDraft(updated);
      setNewNote("");
      dataChanged("*");
    } catch (e) { setError(String(e)); }
  }

  async function removeNote(idx: number) {
    if (!profile) return;
    const next = profile.notes.filter((_, i) => i !== idx);
    try {
      const updated = await patchProfile({ notes: next });
      setProfile(updated);
      setDraft(updated);
      dataChanged("*");
    } catch (e) { setError(String(e)); }
  }

  async function handleReset() {
    if (!confirm("Clear everything the assistant knows about you?")) return;
    try {
      await resetProfile();
      await load();
      dataChanged("*");
    } catch (e) { setError(String(e)); }
  }

  if (!draft) return <p className="muted">Loading...</p>;

  return (
    <div className="col gap-5">
      <div className="hero">
        <h1>Your household</h1>
        <p>
          The assistant uses this to personalise recipes and meal plans. You can edit it directly,
          or just chat — the assistant will pick things up and record them here on its own.
        </p>
      </div>

      <ErrorBanner>{error}</ErrorBanner>

      <div className="row gap-4 wrap items-start">
        {/* Structured fields */}
        <div className="flex-1 min-w-340">
          <Card>
            <h3>Basics</h3>
            <div className="col-2">
              <Field>
                Family size
                <Input
                  type="number" min={1} numeric
                  value={draft.family_size ?? ""}
                  onChange={(e) => updateDraft("family_size", e.target.value === "" ? null : Math.max(1, Number(e.target.value)))}
                />
              </Field>
              <Field>
                Typical cook-time (min)
                <Input
                  type="number" min={5} numeric
                  value={draft.typical_cook_time_min ?? ""}
                  onChange={(e) => updateDraft("typical_cook_time_min", e.target.value === "" ? null : Math.max(5, Number(e.target.value)))}
                />
              </Field>
              <Field>
                Batch-cook preference
                <Select
                  className="w-auto"
                  value={draft.batch_cook_preference ?? ""}
                  onChange={(e) => updateDraft("batch_cook_preference", e.target.value || null)}
                >
                  {BATCH_OPTIONS.map((o) => (
                    <option key={o} value={o}>{o || "(unset)"}</option>
                  ))}
                </Select>
              </Field>
              <Field>
                Budget
                <Select
                  className="w-auto"
                  value={draft.budget_level ?? ""}
                  onChange={(e) => updateDraft("budget_level", e.target.value || null)}
                >
                  {BUDGET_OPTIONS.map((o) => (
                    <option key={o} value={o}>{o || "(unset)"}</option>
                  ))}
                </Select>
              </Field>
              <Field>
                Max non-staple ingredients
                <Input
                  type="number" min={3} max={20} numeric
                  value={draft.max_ingredients_to_buy ?? ""}
                  placeholder="8"
                  onChange={(e) =>
                    updateDraft("max_ingredients_to_buy",
                      e.target.value === "" ? null : Math.max(3, Math.min(20, Number(e.target.value))))
                  }
                />
              </Field>
            </div>

          </Card>

          <Card className="mt-4">
            <h3>Tastes & constraints</h3>
            <p className="small muted">Comma-separated. Allergies are strict; the assistant never includes them.</p>
            <div className="col-2">
              {LIST_FIELDS.map((f) => (
                <Field key={f.key as string} className="field-col">
                  <span className="small">{f.label}</span>
                  <Input
                    placeholder={f.placeholder}
                    value={listDrafts[f.key as string] ?? ""}
                    onChange={(e) => updateListDraft(f.key as string, e.target.value)}
                  />
                </Field>
              ))}
            </div>
          </Card>

          <div className="row gap-2 mt-3">
            <Button onClick={save} disabled={!dirty || saving} variant="primary">
              {saving ? "Saving..." : "Save profile"}
            </Button>
            <Button onClick={handleReset} variant="danger" size="sm" className="ml-auto">
              Reset everything
            </Button>
          </div>
        </div>

        {/* Notes */}
        <div className="flex-1 min-w-340">
          <Card>
            <h3>Assistant notes</h3>
            <p className="small muted">
              Observations the assistant has recorded (or you've added). Things that don't fit a field.
            </p>

            {profile && profile.notes.length === 0 && (
              <Empty>No notes yet — chat with the assistant and it'll learn.</Empty>
            )}
            <div className="col-2">
              {profile?.notes.map((n, i) => (
                <div key={i} className="row gap-2 inset items-start">
                  <span className="flex-1 small">{n}</span>
                  <IconButton onClick={() => removeNote(i)} aria-label="Remove note">
                    <X size={14} />
                  </IconButton>
                </div>
              ))}
            </div>

            <div className="row gap-2 mt-3">
              <Input
                className="flex-1"
                placeholder="Add a note..."
                value={newNote}
                onChange={(e) => setNewNote(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addNote()}
              />
              <Button onClick={addNote} disabled={!newNote.trim()} size="sm">
                <Plus size={14} /> Note
              </Button>
            </div>

            {profile?.updated_at && (
              <p className="tiny muted mt-3">Last updated {profile.updated_at}</p>
            )}
          </Card>
        </div>
      </div>

      <PantrySection />
    </div>
  );
}


function PantrySection() {
  const [items, setItems] = useState<StapleEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [seededNow, setSeededNow] = useState(false);
  const [err, setErr] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const res = await fetchStaples();
      setItems(res.items);
      setSeededNow(res.seeded_now);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);

  async function toggle(fdc_id: number, currentlyIn: boolean) {
    if (currentlyIn) {
      setItems((prev) => prev.filter((i) => i.fdc_id !== fdc_id));
      try { await removeStaple(fdc_id); }
      catch (e) { setErr(e instanceof Error ? e.message : String(e)); void load(); }
    } else {
      try { await addStaple(fdc_id); void load(); }
      catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    }
  }

  const grouped = useMemo(() => {
    const m: Record<string, StapleEntry[]> = {};
    for (const it of items) (m[it.category] ||= []).push(it);
    for (const k of Object.keys(m)) m[k].sort((a, b) => a.name.localeCompare(b.name));
    return m;
  }, [items]);

  return (
    <Card className="mt-4">
      <div className="row gap-2 items-baseline">
        <h3 className="m-0 flex-1">Pantry staples</h3>
        <span className="small muted">{items.length} items · always-have</span>
      </div>
      <p className="small muted">
        These are silently omitted from shopping lists and shown under{" "}
        <em>From your pantry</em> in recipes. Uncheck things you've run out of.
        Use the chat (&ldquo;we ran out of soy sauce&rdquo;) for natural-language edits.
      </p>
      {seededNow && (
        <p className="small">Just seeded from the system list filtered by your cuisines.</p>
      )}
      {err && <ErrorBanner>{err}</ErrorBanner>}
      {loading && <p className="muted">Loading…</p>}
      {!loading && Object.keys(grouped).length === 0 && (
        <Empty>No staples yet.</Empty>
      )}
      <div className="col-2">
        {Object.entries(grouped).map(([cat, list]) => (
          <div key={cat}>
            <h4 className="overline muted m-0 mt-2">{cat}</h4>
            <div className="row wrap gap-2 mt-2">
              {list.map((it) => (
                <button
                  key={it.fdc_id}
                  type="button"
                  className="chip chip-active"
                  onClick={() => toggle(it.fdc_id, true)}
                  title="Click to remove from pantry"
                >
                  {it.name} <X size={11} />
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
