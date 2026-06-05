import { useState } from "react";
import { Button, Modal } from "../components/ui";

interface Props {
  open: boolean;
  onClose: () => void;
}

const EN = (
  <>
    <h3>Privacy Policy</h3>
    <p className="muted">
      <em>Last updated: 26 May 2026</em>
    </p>
    <p>
      This policy explains how Hearth (operated by Andreas Johansson — the
      "Service" or "we"/"us") collects and uses your personal data when you
      use the Hearth meal-planning app at hearth.darkfallcompanion.se.
    </p>
    <h4>Data we collect</h4>
    <ul>
      <li>
        <strong>Account email address</strong> — provided when you sign in
        with Google or via a magic link. Used to authenticate you and send
        transactional emails (sign-in links).
      </li>
      <li>
        <strong>Household data you create</strong> — household name, your
        role, locale, and any profile fields you fill in (family size,
        dietary preferences, allergies, favourite cuisines, etc.).
      </li>
      <li>
        <strong>Recipes, meal plans, shopping templates, and chat history</strong>{" "}
        — content you create or generate via the AI assistant, stored to
        power the service.
      </li>
      <li>
        <strong>Credit-ledger entries</strong> — bookkeeping records of how
        many AI generations you've used, so we can enforce the monthly
        allowance.
      </li>
    </ul>
    <h4>How we use your data</h4>
    <ul>
      <li>To provide the meal-planning, recipe storage, and AI features.</li>
      <li>
        To personalise AI-generated recipes and plans based on your
        household profile.
      </li>
      <li>To enforce per-household usage caps on AI features.</li>
    </ul>
    <h4>Third parties (data processors)</h4>
    <ul>
      <li>
        <strong>Supabase</strong> (Frankfurt, EU): authentication and
        database storage.{" "}
        <a href="https://supabase.com/privacy" target="_blank" rel="noopener noreferrer">
          Supabase privacy policy
        </a>.
      </li>
      <li>
        <strong>OpenAI</strong> (USA): processes the text of your AI
        requests (recipe prompts, chat messages).{" "}
        <a href="https://openai.com/policies/privacy-policy" target="_blank" rel="noopener noreferrer">
          OpenAI privacy policy
        </a>. Transfers to the US occur under OpenAI's Standard Contractual
        Clauses.
      </li>
      <li>
        <strong>Pollinations.ai</strong>: generates recipe images from the
        recipe name. Only the recipe title is sent; no account data.
      </li>
    </ul>
    <h4>Your rights (GDPR)</h4>
    <p>
      You have the right to access, rectify, and erase your personal data,
      and the right to data portability:
    </p>
    <ul>
      <li>
        <strong>Export</strong>: request a JSON dump of all your
        household-scoped data via the app (Household tab → Export). Or by
        email.
      </li>
      <li>
        <strong>Deletion</strong>: delete your account from the app
        (Household tab → Delete account). This removes your email, your
        household membership, and — if you were the last member — the
        household and all its recipes, plans, and chat history. Encrypted
        backups are purged within 30 days.
      </li>
      <li>
        For any other request, contact{" "}
        <a href="mailto:andreas.johansson.91.privat@gmail.com">
          andreas.johansson.91.privat@gmail.com
        </a>.
      </li>
      <li>
        You also have the right to lodge a complaint with the Swedish
        Authority for Privacy Protection (IMY) at{" "}
        <a href="https://www.imy.se/" target="_blank" rel="noopener noreferrer">imy.se</a>.
      </li>
    </ul>
    <h4>Cookies and tracking</h4>
    <p>
      We use only essential authentication cookies (your Supabase session).
      We do not use analytics, advertising, or cross-site tracking cookies.
    </p>
    <h4>Data retention</h4>
    <p>
      Account data is retained while your account is active. After
      deletion, residual copies in encrypted backups are purged within 30
      days.
    </p>
    <h4>Contact</h4>
    <p>
      Data controller: Andreas Johansson, Sweden. Email:{" "}
      <a href="mailto:andreas.johansson.91.privat@gmail.com">
        andreas.johansson.91.privat@gmail.com
      </a>.
    </p>
  </>
);

const SV = (
  <>
    <h3>Integritetspolicy</h3>
    <p className="muted">
      <em>Senast uppdaterad: 26 maj 2026</em>
    </p>
    <p>
      Den här policyn förklarar hur Hearth (drivs av Andreas Johansson —
      "Tjänsten" eller "vi"/"oss") samlar in och använder dina
      personuppgifter när du använder Hearth-appen på
      hearth.darkfallcompanion.se.
    </p>
    <h4>Uppgifter vi samlar in</h4>
    <ul>
      <li>
        <strong>E-postadress till kontot</strong> — anges när du loggar in
        med Google eller via en magisk länk. Används för att autentisera
        dig och skicka inloggningslänkar.
      </li>
      <li>
        <strong>Hushållsdata du skapar</strong> — hushållets namn, din
        roll, språkval och eventuella profilfält du fyller i
        (familjestorlek, kostpreferenser, allergier, favoritkök m.m.).
      </li>
      <li>
        <strong>Recept, matschema, inköpsmallar och chattlogg</strong> —
        innehåll du skapar eller genererar via AI-assistenten, lagrat för
        att driva tjänsten.
      </li>
      <li>
        <strong>Krediträkning</strong> — bokföring av hur många
        AI-genereringar du har använt, så att vi kan begränsa månadens
        kvot.
      </li>
    </ul>
    <h4>Hur vi använder dina uppgifter</h4>
    <ul>
      <li>För att tillhandahålla planerings-, recept- och AI-funktioner.</li>
      <li>
        För att personifiera AI-genererade recept och planer utifrån din
        hushållsprofil.
      </li>
      <li>För att upprätthålla användningsbegränsningar per hushåll.</li>
    </ul>
    <h4>Tredje parter (personuppgiftsbiträden)</h4>
    <ul>
      <li>
        <strong>Supabase</strong> (Frankfurt, EU): autentisering och
        databaslagring.{" "}
        <a href="https://supabase.com/privacy" target="_blank" rel="noopener noreferrer">
          Supabase integritetspolicy
        </a>.
      </li>
      <li>
        <strong>OpenAI</strong> (USA): behandlar text i dina AI-förfrågningar
        (receptbeskrivningar, chattmeddelanden).{" "}
        <a href="https://openai.com/policies/privacy-policy" target="_blank" rel="noopener noreferrer">
          OpenAI integritetspolicy
        </a>. Överföring till USA sker enligt OpenAI:s standardavtalsklausuler.
      </li>
      <li>
        <strong>Pollinations.ai</strong>: genererar receptbilder utifrån
        receptets namn. Endast titeln skickas; inga kontouppgifter.
      </li>
    </ul>
    <h4>Dina rättigheter (GDPR)</h4>
    <p>
      Du har rätt att få tillgång till, rätta och radera dina
      personuppgifter, samt rätt till dataportabilitet:
    </p>
    <ul>
      <li>
        <strong>Export</strong>: begär en JSON-export av alla dina
        hushållsdata via appen (Hushåll → Exportera). Eller per e-post.
      </li>
      <li>
        <strong>Radering</strong>: ta bort kontot från appen (Hushåll →
        Ta bort konto). Det tar bort din e-post, din
        hushållsmedlemsskap, och — om du var sista medlemmen — hushållet
        och alla dess recept, planer och chattloggar. Krypterade
        säkerhetskopior rensas inom 30 dagar.
      </li>
      <li>
        För övriga ärenden, kontakta{" "}
        <a href="mailto:andreas.johansson.91.privat@gmail.com">
          andreas.johansson.91.privat@gmail.com
        </a>.
      </li>
      <li>
        Du har också rätt att lämna in ett klagomål till Integritetsskyddsmyndigheten
        (IMY) på{" "}
        <a href="https://www.imy.se/" target="_blank" rel="noopener noreferrer">imy.se</a>.
      </li>
    </ul>
    <h4>Cookies och spårning</h4>
    <p>
      Vi använder bara nödvändiga autentiseringscookies (din
      Supabase-session). Vi använder inte analys-, annons- eller
      spårningscookies.
    </p>
    <h4>Lagringstid</h4>
    <p>
      Kontouppgifter lagras medan ditt konto är aktivt. Efter radering
      rensas kvarvarande kopior i krypterade säkerhetskopior inom 30 dagar.
    </p>
    <h4>Kontakt</h4>
    <p>
      Personuppgiftsansvarig: Andreas Johansson, Sverige. E-post:{" "}
      <a href="mailto:andreas.johansson.91.privat@gmail.com">
        andreas.johansson.91.privat@gmail.com
      </a>.
    </p>
  </>
);

export default function PrivacyPolicy({ open, onClose }: Props) {
  const [lang, setLang] = useState<"en" | "sv">("en");
  return (
    <Modal open={open} onClose={onClose} title={lang === "en" ? "Privacy Policy" : "Integritetspolicy"}>
      <div className="legal-toggle">
        <Button
          variant={lang === "en" ? "primary" : "ghost"}
          size="sm"
          onClick={() => setLang("en")}
        >
          English
        </Button>
        <Button
          variant={lang === "sv" ? "primary" : "ghost"}
          size="sm"
          onClick={() => setLang("sv")}
        >
          Svenska
        </Button>
      </div>
      <div className="legal-content">{lang === "en" ? EN : SV}</div>
    </Modal>
  );
}
