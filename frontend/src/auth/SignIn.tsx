import { useState } from "react";
import type { FormEvent } from "react";
import { Trans, useTranslation } from "react-i18next";
import { Mail } from "lucide-react";
import { supabase } from "../lib/supabase";
import { Button, Card, ErrorBanner, Field, Input } from "../components/ui";
import PrivacyPolicy from "../legal/PrivacyPolicy";
import TermsOfService from "../legal/TermsOfService";

interface Props {
  redirectTo?: string;
}

export default function SignIn({ redirectTo }: Props) {
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [legalOpen, setLegalOpen] = useState<"privacy" | "terms" | null>(null);

  const target = redirectTo ?? window.location.origin;

  async function signInWithGoogle() {
    setError(null);
    const { error: err } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: target },
    });
    if (err) setError(err.message);
  }

  async function signInWithEmail(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const trimmed = email.trim();
    if (!trimmed) return;
    setSending(true);
    const { error: err } = await supabase.auth.signInWithOtp({
      email: trimmed,
      options: { emailRedirectTo: target },
    });
    setSending(false);
    if (err) {
      setError(err.message);
      return;
    }
    setSent(true);
  }

  return (
    <div className="auth-shell">
      <div className="brand auth-brand">
        <span className="brand-mark">Mealplanner</span>
        <span className="brand-tag">{t("nav.brandTag")}</span>
      </div>

      <Card className="auth-card">
        {error && <ErrorBanner>{error}</ErrorBanner>}

        {sent ? (
          <div className="text-center">
            <Mail size={28} className="auth-icon" />
            <h2 className="mt-3">{t("signin.checkInbox")}</h2>
            <p className="muted mt-2">
              <Trans i18nKey="signin.magicLinkSent" values={{ email }}>
                We sent a magic link to <strong>{email}</strong>. Click it to sign in.
              </Trans>
            </p>
          </div>
        ) : (
          <>
            <Button variant="primary" block onClick={signInWithGoogle}>
              {t("signin.continueWithGoogle")}
            </Button>

            <div className="auth-divider">{t("signin.divider")}</div>

            <form onSubmit={signInWithEmail}>
              <Field>
                <span>{t("signin.emailLabel")}</span>
                <Input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder={t("signin.emailPlaceholder")}
                  required
                  autoFocus
                />
              </Field>
              <Button
                type="submit"
                variant="accent"
                block
                disabled={sending || !email.trim()}
                className="mt-3"
              >
                {sending ? t("signin.sending") : t("signin.sendMagicLink")}
              </Button>
            </form>
          </>
        )}
      </Card>

      <p className="muted text-center auth-legal-foot">
        <Trans
          i18nKey="signin.legalFooter"
          components={{
            terms: <button type="button" className="link-button" onClick={() => setLegalOpen("terms")} />,
            privacy: <button type="button" className="link-button" onClick={() => setLegalOpen("privacy")} />,
          }}
        />
      </p>

      <PrivacyPolicy open={legalOpen === "privacy"} onClose={() => setLegalOpen(null)} />
      <TermsOfService open={legalOpen === "terms"} onClose={() => setLegalOpen(null)} />
    </div>
  );
}
