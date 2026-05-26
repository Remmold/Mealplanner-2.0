import { useState } from "react";
import { Button, Modal } from "../components/ui";

interface Props {
  open: boolean;
  onClose: () => void;
}

const EN = (
  <>
    <h3>Terms of Service</h3>
    <p className="muted">
      <em>Last updated: 26 May 2026</em>
    </p>
    <p>
      These terms govern your use of the Hearth meal-planning service at
      hearth.darkfallcompanion.se. By creating an account you agree to
      these terms.
    </p>
    <h4>The service</h4>
    <p>
      Hearth helps households plan meals, build recipes, and generate
      shopping lists. Some features use AI (OpenAI's language models) to
      generate recipes and chat responses. AI features are subject to a
      monthly per-household credit allowance during the beta.
    </p>
    <h4>Your account</h4>
    <ul>
      <li>
        You must be at least 16 years old to use Hearth (the minimum age
        for unsupervised data processing under GDPR in Sweden).
      </li>
      <li>
        You're responsible for keeping your account credentials safe and
        for activity that happens under your account.
      </li>
      <li>
        One person, one account. Households may have multiple members; each
        member must have their own account.
      </li>
    </ul>
    <h4>Acceptable use</h4>
    <p>You agree not to:</p>
    <ul>
      <li>
        Use the AI features to generate illegal, harmful, hateful, sexually
        explicit, or medically/legally advisory content.
      </li>
      <li>
        Probe, scan, scrape, or attempt to bypass the credit allowance or
        rate limits.
      </li>
      <li>
        Use Hearth to send unsolicited messages or otherwise abuse other
        users.
      </li>
      <li>Reverse engineer, copy, or resell the service.</li>
    </ul>
    <h4>AI-generated content</h4>
    <p>
      AI-generated recipes, meal plans, and chat replies are produced by a
      third-party language model and may contain inaccuracies. They are
      <strong> not nutritional, medical, or dietary advice</strong>. Always
      check ingredients against your own allergies and health needs,
      especially if you have a medical condition. Do not rely on Hearth to
      ensure safety of food, allergens, or dietary restrictions in
      real-world cooking.
    </p>
    <h4>Service availability</h4>
    <p>
      Hearth is offered as a beta. We may change, suspend, or discontinue
      features at any time. We aim to provide reasonable uptime but make
      no SLA guarantees. AI features may be temporarily unavailable when
      the monthly platform-wide budget is exhausted.
    </p>
    <h4>Termination</h4>
    <p>
      You may delete your account at any time from the app. We may suspend
      or terminate accounts that violate these terms.
    </p>
    <h4>Liability</h4>
    <p>
      To the extent permitted by Swedish law, Hearth is provided "as is"
      without warranty. We're not liable for indirect or consequential
      damages arising from use of the service. This does not limit
      liability for gross negligence, intent, or anything that cannot be
      excluded under mandatory Swedish consumer law.
    </p>
    <h4>Changes to these terms</h4>
    <p>
      We may update these terms. Material changes will be announced in the
      app at least 14 days before they take effect.
    </p>
    <h4>Governing law</h4>
    <p>
      These terms are governed by Swedish law. Disputes are resolved by
      Swedish courts, subject to your mandatory consumer protections.
    </p>
    <h4>Contact</h4>
    <p>
      Operator: Andreas Johansson, Sweden. Email:{" "}
      <a href="mailto:andreas.johansson.91.privat@gmail.com">
        andreas.johansson.91.privat@gmail.com
      </a>.
    </p>
  </>
);

const SV = (
  <>
    <h3>Användarvillkor</h3>
    <p className="muted">
      <em>Senast uppdaterad: 26 maj 2026</em>
    </p>
    <p>
      Dessa villkor styr din användning av Hearth-tjänsten på
      hearth.darkfallcompanion.se. Genom att skapa ett konto godkänner du
      villkoren.
    </p>
    <h4>Tjänsten</h4>
    <p>
      Hearth hjälper hushåll planera måltider, bygga recept och generera
      inköpslistor. Vissa funktioner använder AI (OpenAI:s språkmodeller)
      för att generera recept och chattsvar. AI-funktionerna omfattas av
      en månadsvis kredittilldelning per hushåll under betatestperioden.
    </p>
    <h4>Ditt konto</h4>
    <ul>
      <li>
        Du måste vara minst 16 år för att använda Hearth (åldersgräns för
        oövervakad uppgiftsbehandling enligt GDPR i Sverige).
      </li>
      <li>
        Du ansvarar för att hålla dina inloggningsuppgifter säkra och för
        aktivitet under ditt konto.
      </li>
      <li>
        En person, ett konto. Hushåll får ha flera medlemmar; varje medlem
        måste ha sitt eget konto.
      </li>
    </ul>
    <h4>Acceptabel användning</h4>
    <p>Du förbinder dig att inte:</p>
    <ul>
      <li>
        Använda AI-funktioner för att generera olagligt, skadligt,
        hatfullt, sexuellt explicit eller medicinskt/juridiskt rådgivande
        innehåll.
      </li>
      <li>
        Söka, skanna, skrapa eller försöka kringgå kreditgränserna eller
        hastighetsbegränsningarna.
      </li>
      <li>
        Använda Hearth för att skicka oönskade meddelanden eller på annat
        sätt missbruka andra användare.
      </li>
      <li>Omkonstruera, kopiera eller sälja tjänsten.</li>
    </ul>
    <h4>AI-genererat innehåll</h4>
    <p>
      AI-genererade recept, måltidsplaner och chattsvar produceras av en
      språkmodell från tredje part och kan innehålla felaktigheter. De är
      <strong> inte närings-, medicinska eller dietråd</strong>. Kontrollera
      alltid ingredienser mot dina egna allergier och hälsobehov, särskilt
      om du har ett medicinskt tillstånd. Förlita dig inte på Hearth för
      att säkerställa matsäkerhet, allergener eller kostrestriktioner i
      verklig matlagning.
    </p>
    <h4>Tjänstens tillgänglighet</h4>
    <p>
      Hearth erbjuds som en beta. Vi kan ändra, pausa eller avveckla
      funktioner när som helst. Vi strävar efter rimlig drifttid men ger
      inga SLA-garantier. AI-funktioner kan tillfälligt vara otillgängliga
      när månadens plattformsbudget har förbrukats.
    </p>
    <h4>Uppsägning</h4>
    <p>
      Du kan radera ditt konto när som helst via appen. Vi kan pausa eller
      avsluta konton som bryter mot villkoren.
    </p>
    <h4>Ansvar</h4>
    <p>
      I den utsträckning som tillåts enligt svensk lag tillhandahålls
      Hearth "i befintligt skick" utan garanti. Vi ansvarar inte för
      indirekta eller följdskador som uppstår vid användning av tjänsten.
      Detta begränsar inte ansvar för grov vårdslöshet, uppsåt eller annat
      som inte kan undantas enligt tvingande svensk konsumenträtt.
    </p>
    <h4>Ändringar i villkoren</h4>
    <p>
      Vi kan uppdatera villkoren. Väsentliga ändringar kommer att
      annonseras i appen minst 14 dagar innan de träder i kraft.
    </p>
    <h4>Tillämplig lag</h4>
    <p>
      Villkoren styrs av svensk lag. Tvister avgörs av svenska domstolar,
      med förbehåll för dina tvingande konsumenträttigheter.
    </p>
    <h4>Kontakt</h4>
    <p>
      Operatör: Andreas Johansson, Sverige. E-post:{" "}
      <a href="mailto:andreas.johansson.91.privat@gmail.com">
        andreas.johansson.91.privat@gmail.com
      </a>.
    </p>
  </>
);

export default function TermsOfService({ open, onClose }: Props) {
  const [lang, setLang] = useState<"en" | "sv">("en");
  return (
    <Modal open={open} onClose={onClose} title={lang === "en" ? "Terms of Service" : "Användarvillkor"}>
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
