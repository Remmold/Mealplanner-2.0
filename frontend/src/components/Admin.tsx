// Personal admin back-office. English-only by design (only the admin sees it).
// Gated server-side by require_admin AND in App.tsx by me.is_admin — both.
import { useEffect, useState } from "react";
import { Button, Card, Empty, ErrorBanner, Input, Textarea } from "./ui";
import {
  fetchAdminIngredients,
  fetchAdminRecipes,
  reloadCatalog,
  saveAdminIngredient,
  saveAdminRecipeTranslations,
  type AdminIngredient,
  type AdminLocaleContent,
  type AdminRecipeTranslation,
} from "../lib/auth-api";

function clean(c: AdminLocaleContent): AdminLocaleContent {
  return { name: c.name.trim(), instructions: c.instructions.map((s) => s.trim()).filter(Boolean) };
}

export default function Admin() {
  const [recipes, setRecipes] = useState<AdminRecipeTranslation[] | null>(null);
  const [error, setError] = useState("");
  const [catalogMsg, setCatalogMsg] = useState("");

  useEffect(() => {
    fetchAdminRecipes()
      .then(setRecipes)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  async function handleReload() {
    setCatalogMsg("");
    try {
      const r = await reloadCatalog();
      setCatalogMsg(`Reloaded — ${r.pantry} pantry items`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="col gap-5">
      <div className="hero">
        <h1>Admin</h1>
        <p>Back-office for translations and catalog data — only you can see this.</p>
      </div>

      <ErrorBanner>{error}</ErrorBanner>

      <Card>
        <div className="row gap-2 items-center">
          <h3 className="flex-1">Recipe translations</h3>
          <Button size="sm" onClick={handleReload}>Reload catalog</Button>
        </div>
        {catalogMsg && <p className="small muted">{catalogMsg}</p>}
        <p className="small muted">
          Edit the English and Swedish name + steps for each recipe in your household.
          One step per line.
        </p>

        {recipes === null && <p className="muted mt-3">Loading…</p>}
        {recipes && recipes.length === 0 && <Empty>No recipes in your household yet.</Empty>}

        <div className="col gap-4 mt-3">
          {recipes?.map((r) => (
            <RecipeRow key={r.id} recipe={r} onError={setError} />
          ))}
        </div>
      </Card>

      <IngredientsPanel onError={setError} />
    </div>
  );
}

function IngredientsPanel({ onError }: { onError: (s: string) => void }) {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<AdminIngredient[] | null>(null);

  async function search(query: string) {
    setItems(null);
    try {
      setItems(await fetchAdminIngredients(query));
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    void search("");
  }, []);

  return (
    <Card>
      <h3>Ingredient names (EN / SV)</h3>
      <p className="small muted">
        Search the curated pantry and edit the English + Swedish display names.
        Saving updates Supabase and reloads the catalog.
      </p>
      <div className="row gap-2 mt-2">
        <Input
          className="flex-1"
          placeholder="Search ingredients…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && search(q)}
        />
        <Button size="sm" onClick={() => search(q)}>Search</Button>
      </div>
      {items === null && <p className="muted mt-3">Loading…</p>}
      {items && items.length === 0 && <Empty>No matches.</Empty>}
      <div className="col gap-2 mt-3">
        {items?.map((it) => (
          <IngredientRow key={it.fdc_id} item={it} onError={onError} />
        ))}
      </div>
    </Card>
  );
}

function IngredientRow({ item, onError }: { item: AdminIngredient; onError: (s: string) => void }) {
  const [en, setEn] = useState(item.simple_name);
  const [sv, setSv] = useState(item.name_sv ?? "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  async function save() {
    setSaving(true);
    setSaved(false);
    try {
      await saveAdminIngredient(item.fdc_id, { simple_name: en, name_sv: sv.trim() || null });
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="row gap-2 wrap items-center inset">
      <Input className="flex-1 min-w-100" value={en} onChange={(e) => setEn(e.target.value)} />
      <Input
        className="flex-1 min-w-100"
        placeholder="(Swedish)"
        value={sv}
        onChange={(e) => setSv(e.target.value)}
      />
      <span className="tiny muted">{item.category}</span>
      <Button size="sm" variant="primary" onClick={save} disabled={saving}>
        {saving ? "…" : "Save"}
      </Button>
      {saved && <span className="tiny muted">Saved</span>}
    </div>
  );
}

function RecipeRow({
  recipe,
  onError,
}: {
  recipe: AdminRecipeTranslation;
  onError: (s: string) => void;
}) {
  const [en, setEn] = useState<AdminLocaleContent>(recipe.en);
  const [sv, setSv] = useState<AdminLocaleContent>(recipe.sv);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  async function save() {
    setSaving(true);
    setSaved(false);
    try {
      await saveAdminRecipeTranslations(recipe.id, clean(en), clean(sv));
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card variant="soft">
      <p className="small muted">{recipe.base_name}</p>
      <div className="row gap-4 wrap items-start mt-2">
        <LocaleEditor title="English" value={en} onChange={setEn} />
        <LocaleEditor title="Svenska" value={sv} onChange={setSv} />
      </div>
      <div className="row gap-2 mt-3 items-center">
        <Button size="sm" variant="primary" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </Button>
        {saved && <span className="small muted">Saved</span>}
      </div>
    </Card>
  );
}

function LocaleEditor({
  title,
  value,
  onChange,
}: {
  title: string;
  value: AdminLocaleContent;
  onChange: (v: AdminLocaleContent) => void;
}) {
  return (
    <div className="flex-1 min-w-300">
      <p className="small">{title}</p>
      <Input value={value.name} onChange={(e) => onChange({ ...value, name: e.target.value })} />
      <Textarea
        className="mt-2"
        rows={6}
        value={value.instructions.join("\n")}
        onChange={(e) => onChange({ ...value, instructions: e.target.value.split("\n") })}
      />
    </div>
  );
}
