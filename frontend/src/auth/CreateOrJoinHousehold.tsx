import { useEffect, useState } from "react";
import type { FormEvent } from "react";
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
        <span className="brand-mark">Hearth</span>
        <span className="brand-tag">your kitchen, planned</span>
      </div>

      <Card className="auth-card">
        {error && <ErrorBanner>{error}</ErrorBanner>}

        {mode === "choose" && (
          <>
            <h2 className="text-center">Set up your household</h2>
            <p className="muted text-center">Cook, plan, and shop together.</p>

            <Button variant="primary" block onClick={() => setMode("create")}>
              <Home size={16} />
              <span className="ml-2">Create a new household</span>
            </Button>
            <Button variant="default" block onClick={() => setMode("join")}>
              <Users size={16} />
              <span className="ml-2">Join with an invite link</span>
            </Button>
          </>
        )}

        {mode === "create" && (
          <form onSubmit={handleCreate}>
            <h2>Create a household</h2>
            <Field className="mt-3">
              <span>Household name</span>
              <Input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="The Johansson kitchen"
                required
                autoFocus
                maxLength={120}
              />
            </Field>
            <Field className="mt-3">
              <span>Language</span>
              <Select value={locale} onChange={(e) => setLocale(e.target.value as Locale)}>
                <option value="en">English</option>
                <option value="sv">Svenska</option>
              </Select>
            </Field>
            <div className="mt-4 auth-actions">
              <Button variant="ghost" onClick={() => setMode("choose")} disabled={busy}>
                Back
              </Button>
              <Button
                type="submit"
                variant="primary"
                disabled={busy || !name.trim()}
                className="flex-1"
              >
                {busy ? "Creating..." : "Create household"}
              </Button>
            </div>
          </form>
        )}

        {mode === "join" && (
          <form onSubmit={handleJoin}>
            <h2>Join a household</h2>
            <Field className="mt-3">
              <span>Invite token</span>
              <Input
                type="text"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="From the invite link"
                required
                autoFocus
              />
            </Field>
            <Field className="mt-3">
              <span>Language</span>
              <Select value={locale} onChange={(e) => setLocale(e.target.value as Locale)}>
                <option value="en">English</option>
                <option value="sv">Svenska</option>
              </Select>
            </Field>
            <div className="mt-4 auth-actions">
              <Button variant="ghost" onClick={() => setMode("choose")} disabled={busy}>
                Back
              </Button>
              <Button
                type="submit"
                variant="primary"
                disabled={busy || !token.trim()}
                className="flex-1"
              >
                {busy ? "Joining..." : "Join household"}
              </Button>
            </div>
          </form>
        )}
      </Card>
    </div>
  );
}
