// i18next setup. Resources are bundled inline (no http backend), so init is
// synchronous and useTranslation() is ready on first render — no Suspense.
// Language resolution: explicit per-device choice (localStorage 'hearth.lang')
// wins; otherwise we fall back to the household locale (applied from App once
// `me` loads) and finally the browser language. caches:[] keeps the detector
// from persisting a navigator guess, so the household default can still win.
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import en from "./locales/en";
import sv from "./locales/sv";

export const LANG_STORAGE_KEY = "hearth.lang";

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      sv: { translation: sv },
    },
    fallbackLng: "en",
    supportedLngs: ["en", "sv"],
    interpolation: { escapeValue: false },
    detection: {
      order: ["localStorage", "navigator"],
      lookupLocalStorage: LANG_STORAGE_KEY,
      caches: [],
    },
  });

export default i18n;
