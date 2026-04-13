import { useEffect, useState } from "react";
import {
  fetchProfile,
  patchProfile,
  resetProfile,
  onDataChanged,
  dataChanged,
  type HouseholdProfile,
  type ProfilePatch,
} from "../api";

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

      {error && <div className="error">{error}</div>}

      <div className="row gap-4" style={{ alignItems: "flex-start", flexWrap: "wrap" }}>
        {/* Structured fields */}
        <div className="flex-1" style={{ minWidth: 340 }}>
          <div className="card">
            <h3>Basics</h3>
            <div className="col-2">
              <label className="field">
                Family size
                <input
                  type="number" min={1}
                  className="input input-num"
                  value={draft.family_size ?? ""}
                  onChange={(e) => updateDraft("family_size", e.target.value === "" ? null : Math.max(1, Number(e.target.value)))}
                />
              </label>
              <label className="field">
                Typical cook-time (min)
                <input
                  type="number" min={5}
                  className="input input-num"
                  value={draft.typical_cook_time_min ?? ""}
                  onChange={(e) => updateDraft("typical_cook_time_min", e.target.value === "" ? null : Math.max(5, Number(e.target.value)))}
                />
              </label>
              <label className="field">
                Batch-cook preference
                <select
                  className="select"
                  value={draft.batch_cook_preference ?? ""}
                  onChange={(e) => updateDraft("batch_cook_preference", e.target.value || null)}
                  style={{ width: "auto" }}
                >
                  {BATCH_OPTIONS.map((o) => (
                    <option key={o} value={o}>{o || "(unset)"}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                Budget
                <select
                  className="select"
                  value={draft.budget_level ?? ""}
                  onChange={(e) => updateDraft("budget_level", e.target.value || null)}
                  style={{ width: "auto" }}
                >
                  {BUDGET_OPTIONS.map((o) => (
                    <option key={o} value={o}>{o || "(unset)"}</option>
                  ))}
                </select>
              </label>
            </div>
          </div>

          <div className="card mt-4">
            <h3>Tastes & constraints</h3>
            <p className="small muted">Comma-separated. Allergies are strict; the assistant never includes them.</p>
            <div className="col-2">
              {LIST_FIELDS.map((f) => (
                <label key={f.key as string} className="field" style={{ flexDirection: "column", alignItems: "flex-start" }}>
                  <span className="small">{f.label}</span>
                  <input
                    className="input"
                    placeholder={f.placeholder}
                    value={listDrafts[f.key as string] ?? ""}
                    onChange={(e) => updateListDraft(f.key as string, e.target.value)}
                    style={{ width: "100%" }}
                  />
                </label>
              ))}
            </div>
          </div>

          <div className="row gap-2 mt-3">
            <button onClick={save} disabled={!dirty || saving} className="btn btn-primary">
              {saving ? "Saving..." : "Save profile"}
            </button>
            <button onClick={handleReset} className="btn btn-danger btn-sm" style={{ marginLeft: "auto" }}>
              Reset everything
            </button>
          </div>
        </div>

        {/* Notes */}
        <div className="flex-1" style={{ minWidth: 340 }}>
          <div className="card">
            <h3>Assistant notes</h3>
            <p className="small muted">
              Observations the assistant has recorded (or you've added). Things that don't fit a field.
            </p>

            {profile && profile.notes.length === 0 && (
              <div className="empty">No notes yet — chat with the assistant and it'll learn.</div>
            )}
            <div className="col-2">
              {profile?.notes.map((n, i) => (
                <div key={i} className="row gap-2" style={{
                  padding: 10, background: "var(--cream-2)", borderRadius: "var(--r-sm)",
                  alignItems: "flex-start",
                }}>
                  <span className="flex-1 small">{n}</span>
                  <button onClick={() => removeNote(i)} className="icon-btn">×</button>
                </div>
              ))}
            </div>

            <div className="row gap-2 mt-3">
              <input
                className="input flex-1"
                placeholder="Add a note..."
                value={newNote}
                onChange={(e) => setNewNote(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addNote()}
              />
              <button onClick={addNote} disabled={!newNote.trim()} className="btn btn-sm">+ Note</button>
            </div>

            {profile?.updated_at && (
              <p className="tiny muted mt-3">Last updated {profile.updated_at}</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
