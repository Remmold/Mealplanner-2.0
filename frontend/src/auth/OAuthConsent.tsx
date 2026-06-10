import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ShieldCheck } from "lucide-react";
import { supabase } from "../lib/supabase";
import { Button, Card, ErrorBanner, Pill } from "../components/ui";

// Subset of Supabase's OAuthAuthorizationDetails we render. Structurally
// assignable from the SDK type, so we avoid depending on its import path.
interface ConsentDetails {
  authorization_id: string;
  client: { name: string };
  redirect_uri: string;
  scope: string;
  user: { email: string };
}

// The consent screen Supabase's OAuth 2.1 server redirects to (Authorization
// Path = /oauth/consent). It reads the pending authorization, shows the user who
// is asking, and approves/denies — Supabase then issues the code and bounces the
// user back to the MCP client. Requires a Supabase session (handled in App).
export default function OAuthConsent() {
  const { t } = useTranslation();
  const [details, setDetails] = useState<ConsentDetails | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const authorizationId = new URLSearchParams(window.location.search).get("authorization_id");

  useEffect(() => {
    let cancelled = false;
    if (!authorizationId) {
      setError(t("connector.missingId"));
      setLoading(false);
      return;
    }
    void (async () => {
      // Keep the discriminated union intact (don't destructure) so `res.data`
      // narrows after the error guard.
      const res = await supabase.auth.oauth.getAuthorizationDetails(authorizationId);
      if (cancelled) return;
      if (res.error) {
        setError(res.error.message);
        setLoading(false);
        return;
      }
      if ("redirect_url" in res.data) {
        window.location.href = res.data.redirect_url; // already consented
        return;
      }
      setDetails(res.data);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [authorizationId, t]);

  async function decide(approve: boolean) {
    if (!authorizationId) return;
    setBusy(true);
    setError(null);
    const res = approve
      ? await supabase.auth.oauth.approveAuthorization(authorizationId, { skipBrowserRedirect: true })
      : await supabase.auth.oauth.denyAuthorization(authorizationId, { skipBrowserRedirect: true });
    if (res.error) {
      setError(res.error.message);
      setBusy(false);
      return;
    }
    window.location.href = res.data.redirect_url;
  }

  const clientName = details?.client.name || t("connector.unknownClient");
  const scopes = details?.scope ? details.scope.split(" ").filter(Boolean) : [];
  let redirectHost = "";
  if (details?.redirect_uri) {
    try {
      redirectHost = new URL(details.redirect_uri).host;
    } catch {
      redirectHost = details.redirect_uri;
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

        {loading ? (
          <p className="muted text-center">{t("connector.loading")}</p>
        ) : details ? (
          <>
            <div className="text-center">
              <ShieldCheck size={28} className="auth-icon" />
              <h2 className="mt-3">{t("connector.title")}</h2>
              <p className="muted mt-2">{t("connector.intro", { client: clientName })}</p>
              <p className="muted mt-2">{t("connector.signedInAs", { email: details.user.email })}</p>
            </div>

            <p className="mt-3">{t("connector.grants")}</p>

            {scopes.length > 0 && (
              <div className="row wrap mt-2">
                {scopes.map((s) => (
                  <Pill key={s}>{s}</Pill>
                ))}
              </div>
            )}

            {redirectHost && (
              <p className="muted text-center mt-3">
                {t("connector.redirectNote", { host: redirectHost })}
              </p>
            )}

            <Button
              variant="primary"
              block
              disabled={busy}
              className="mt-3"
              onClick={() => decide(true)}
            >
              {busy ? t("connector.working") : t("connector.approve")}
            </Button>
            <Button
              variant="ghost"
              block
              disabled={busy}
              className="mt-2"
              onClick={() => decide(false)}
            >
              {t("connector.deny")}
            </Button>
          </>
        ) : null}
      </Card>
    </div>
  );
}
