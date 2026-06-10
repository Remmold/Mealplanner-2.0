import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Home, Users } from "lucide-react";
import { Button, Card, ErrorBanner, Field, Input, Select } from "../components/ui";
import { createHousehold, joinHouseholdByToken } from "../lib/auth-api";
import type { Locale } from "../lib/auth-api";
import { useAuth } from "./AuthProvider";

interface Props {
  pendingInviteToken: string | null;
  onPendingTokenConsumed: () => void;
}

type Mode = "choose" | "create" | "join";

export default function CreateOrJoinHousehold({
  pendingInviteToken,
  onPendingTokenConsumed,
}: Props) {
  const { t } = useTranslation();
  const { refreshMe } = useAuth();
  const [mode, setMode] = useState<Mode>(pendingInviteToken ? "join" : "choose");
  const [name, setName] = useState("");
  const [token, setToken] = useState(pendingInviteToken ?? "");
  const [locale, setLocale] = useState<Locale>("en");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // If a token arrives later (after login), pre-fill it.
  useEffect(() => {
    if (pendingInviteToken && !token) setToken(pendingInviteToken);
  }, [pendingInviteToken, token]);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!name.trim()) return;
    setBusy(true);
    try {
      await createHousehold(name.trim(), locale);
      await refreshMe();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleJoin(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!token.trim()) return;
    setBusy(true);
    try {
      await joinHouseholdByToken(token.trim(), locale);
      onPendingTokenConsumed();
      await refreshMe();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-shell">
      <div className="brand auth-brand">
        <span className="brand-mark">Mealplanner</span>
        <span className="brand-tag">{t("nav.brandTag")}</span>
      </div>

      <Card className="auth-card">
        {error && <ErrorBanner>{error}</ErrorBanner>}

        {mode === "choose" && (
          <>
            <h2 className="text-center">{t("household.setupTitle")}</h2>
            <p className="muted text-center">{t("household.setupSubtitle")}</p>

            <Button variant="primary" block onClick={() => setMode("create")}>
              <Home size={16} />
              <span className="ml-2">{t("household.createOption")}</span>
            </Button>
            <Button variant="default" block onClick={() => setMode("join")}>
              <Users size={16} />
              <span className="ml-2">{t("household.joinOption")}</span>
            </Button>
          </>
        )}

        {mode === "create" && (
          <form onSubmit={handleCreate}>
            <h2>{t("household.createTitle")}</h2>
            <Field className="mt-3">
              <span>{t("household.nameLabel")}</span>
              <Input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t("household.namePlaceholder")}
                required
                autoFocus
                maxLength={120}
              />
            </Field>
            <Field className="mt-3">
              <span>{t("nav.language")}</span>
              <Select
                value={locale}
                onChange={(v) => setLocale(v as Locale)}
                options={[
                  { value: "en", label: "English" },
                  { value: "sv", label: "Svenska" },
                ]}
                aria-label={t("nav.language")}
              />
            </Field>
            <div className="mt-4 auth-actions">
              <Button variant="ghost" onClick={() => setMode("choose")} disabled={busy}>
                {t("common.back")}
              </Button>
              <Button
                type="submit"
                variant="primary"
                disabled={busy || !name.trim()}
                className="flex-1"
              >
                {busy ? t("household.creating") : t("household.createSubmit")}
              </Button>
            </div>
          </form>
        )}

        {mode === "join" && (
          <form onSubmit={handleJoin}>
            <h2>{t("household.joinTitle")}</h2>
            <Field className="mt-3">
              <span>{t("household.tokenLabel")}</span>
              <Input
                type="text"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder={t("household.tokenPlaceholder")}
                required
                autoFocus
              />
            </Field>
            <Field className="mt-3">
              <span>{t("nav.language")}</span>
              <Select
                value={locale}
                onChange={(v) => setLocale(v as Locale)}
                options={[
                  { value: "en", label: "English" },
                  { value: "sv", label: "Svenska" },
                ]}
                aria-label={t("nav.language")}
              />
            </Field>
            <div className="mt-4 auth-actions">
              <Button variant="ghost" onClick={() => setMode("choose")} disabled={busy}>
                {t("common.back")}
              </Button>
              <Button
                type="submit"
                variant="primary"
                disabled={busy || !token.trim()}
                className="flex-1"
              >
                {busy ? t("household.joining") : t("household.joinSubmit")}
              </Button>
            </div>
          </form>
        )}
      </Card>
    </div>
  );
}
