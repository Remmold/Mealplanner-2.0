import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, Copy, Plus, UserPlus, X } from "lucide-react";
import {
  fetchProfile,
  patchProfile,
  resetProfile,
  onDataChanged,
  dataChanged,
  type HouseholdProfile,
  type ProfilePatch,
} from "../api";
import { Button, Card, Empty, ErrorBanner, Field, IconButton, Input, Select } from "./ui";
import { useEnumLabels } from "../i18n/enums";
import { useAuth } from "../auth/AuthProvider";
import { createInvite, leaveHousehold } from "../lib/auth-api";

type ListField = { key: keyof HouseholdProfile; label: string; placeholder: string };

function listFields(t: import("i18next").TFunction): ListField[] {
  return [
    { key: "dietary", label: t("profile.dietaryLabel"), placeholder: t("profile.dietaryPlaceholder") },
    { key: "allergies", label: t("profile.allergiesLabel"), placeholder: t("profile.allergiesPlaceholder") },
    { key: "dislikes", label: t("profile.dislikesLabel"), placeholder: t("profile.dislikesPlaceholder") },
    { key: "likes", label: t("profile.likesLabel"), placeholder: t("profile.likesPlaceholder") },
    { key: "cuisines", label: t("profile.cuisinesLabel"), placeholder: t("profile.cuisinesPlaceholder") },
    { key: "kitchen_equipment", label: t("profile.kitchenEquipmentLabel"), placeholder: t("profile.kitchenEquipmentPlaceholder") },
  ];
}

const LIST_FIELD_KEYS: (keyof HouseholdProfile)[] = [
  "dietary", "allergies", "dislikes", "likes", "cuisines", "kitchen_equipment",
];

const BATCH_OPTIONS = ["", "none", "moderate", "heavy"];
const BUDGET_OPTIONS = ["", "thrifty", "moderate", "splurge"];

function splitCsv(s: string): string[] {
  return s.split(",").map((x) => x.trim()).filter(Boolean);
}

export default function Profile() {
  const { t } = useTranslation();
  const el = useEnumLabels();
  const { me, refreshMe } = useAuth();
  const [profile, setProfile] = useState<HouseholdProfile | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  // Household membership (invite a member / leave) lives on this tab.
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const [inviting, setInviting] = useState(false);
  const [copied, setCopied] = useState(false);
  const [leaving, setLeaving] = useState(false);

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
      for (const key of LIST_FIELD_KEYS) {
        patch[key as keyof ProfilePatch] = splitCsv(listDrafts[key] ?? "") as never;
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
    if (!confirm(t("profile.resetConfirm"))) return;
    try {
      await resetProfile();
      await load();
      dataChanged("*");
    } catch (e) { setError(String(e)); }
  }

  async function handleInvite() {
    if (!me || !me.household) return;
    setInviting(true); setError(""); setCopied(false);
    try {
      const res = await createInvite(me.household.id);
      setInviteUrl(res.join_url);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setInviting(false); }
  }

  async function copyInvite() {
    if (!inviteUrl) return;
    try {
      await navigator.clipboard.writeText(inviteUrl);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch { /* clipboard blocked — the field is selectable as a fallback */ }
  }

  async function handleLeave() {
    if (!me || !me.household) return;
    if (!confirm(t("household.leaveConfirm"))) return;
    setLeaving(true); setError("");
    try {
      await leaveHousehold(me.household.id, me.user_id);
      await refreshMe();   // household -> null -> App routes to the create/join screen
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setLeaving(false);
    }
  }

  if (!draft) return <p className="muted">{t("profile.loading")}</p>;

  return (
    <div className="col gap-5">
      <div className="hero">
        <h1>{t("profile.heroTitle")}</h1>
        <p>{t("profile.heroIntro")}</p>
      </div>

      <ErrorBanner>{error}</ErrorBanner>

      {me?.household && (
        <Card>
          <h3>{t("household.manageTitle")}</h3>
          <p className="small muted">
            {me.household.name} · {t("household.memberCount", { count: me.household.member_count })}
          </p>
          <p className="small mt-2">{t("household.inviteIntro")}</p>

          <div className="row gap-2 mt-3 wrap items-center">
            <Button onClick={handleInvite} disabled={inviting}>
              <UserPlus size={14} /> {inviting ? t("household.inviting") : t("household.inviteButton")}
            </Button>
            <Button
              variant="danger"
              size="sm"
              onClick={handleLeave}
              disabled={leaving}
              className="ml-auto"
            >
              {leaving ? t("household.leaving") : t("household.leaveButton")}
            </Button>
          </div>

          {inviteUrl && (
            <>
              <div className="row gap-2 mt-3 items-center">
                <Input
                  className="flex-1"
                  readOnly
                  value={inviteUrl}
                  onFocus={(e) => e.currentTarget.select()}
                />
                <IconButton onClick={copyInvite} aria-label={t("household.copyLink")}>
                  {copied ? <Check size={16} /> : <Copy size={16} />}
                </IconButton>
              </div>
              <p className="tiny muted mt-1">{t("household.inviteHint")}</p>
            </>
          )}
        </Card>
      )}

      <div className="row gap-4 wrap items-start">
        {/* Structured fields */}
        <div className="flex-1 min-w-340">
          <Card>
            <h3>{t("profile.basicsTitle")}</h3>
            <div className="col-2">
              <Field>
                {t("profile.familySize")}
                <Input
                  type="number" min={1} numeric
                  value={draft.family_size ?? ""}
                  onChange={(e) => updateDraft("family_size", e.target.value === "" ? null : Math.max(1, Number(e.target.value)))}
                />
              </Field>
              <Field>
                {t("profile.typicalCookTime")}
                <Input
                  type="number" min={5} numeric
                  value={draft.typical_cook_time_min ?? ""}
                  onChange={(e) => updateDraft("typical_cook_time_min", e.target.value === "" ? null : Math.max(5, Number(e.target.value)))}
                />
              </Field>
              <Field>
                {t("profile.batchCookPreference")}
                <Select
                  className="w-auto"
                  value={draft.batch_cook_preference ?? ""}
                  onChange={(v) => updateDraft("batch_cook_preference", v || null)}
                  options={BATCH_OPTIONS.map((o) => ({
                    value: o,
                    label: o ? el.batch(o) : t("profile.unset"),
                  }))}
                />
              </Field>
              <Field>
                {t("profile.budget")}
                <Select
                  className="w-auto"
                  value={draft.budget_level ?? ""}
                  onChange={(v) => updateDraft("budget_level", v || null)}
                  options={BUDGET_OPTIONS.map((o) => ({
                    value: o,
                    label: o ? el.budget(o) : t("profile.unset"),
                  }))}
                />
              </Field>
              <Field>
                {t("profile.maxNonStapleIngredients")}
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
            <h3>{t("profile.tastesTitle")}</h3>
            <p className="small muted">{t("profile.tastesHint")}</p>
            <div className="col-2">
              {listFields(t).map((f) => (
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
              {saving ? t("common.saving") : t("profile.saveProfile")}
            </Button>
            <Button onClick={handleReset} variant="danger" size="sm" className="ml-auto">
              {t("profile.resetEverything")}
            </Button>
          </div>
        </div>

        {/* Notes */}
        <div className="flex-1 min-w-340">
          <Card>
            <h3>{t("profile.notesTitle")}</h3>
            <p className="small muted">{t("profile.notesHint")}</p>

            {profile && profile.notes.length === 0 && (
              <Empty>{t("profile.notesEmpty")}</Empty>
            )}
            <div className="col-2">
              {profile?.notes.map((n, i) => (
                <div key={i} className="row gap-2 inset items-start">
                  <span className="flex-1 small">{n}</span>
                  <IconButton onClick={() => removeNote(i)} aria-label={t("profile.removeNote")}>
                    <X size={14} />
                  </IconButton>
                </div>
              ))}
            </div>

            <div className="row gap-2 mt-3">
              <Input
                className="flex-1"
                placeholder={t("profile.addNotePlaceholder")}
                value={newNote}
                onChange={(e) => setNewNote(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addNote()}
              />
              <Button onClick={addNote} disabled={!newNote.trim()} size="sm">
                <Plus size={14} /> {t("profile.noteButton")}
              </Button>
            </div>

            {profile?.updated_at && (
              <p className="tiny muted mt-3">{t("profile.lastUpdated", { date: profile.updated_at })}</p>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
