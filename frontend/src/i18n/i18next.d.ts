// Makes t() keys type-checked against the English resource: an unknown key or a
// key missing from a locale is a compile error.
import "i18next";
import type { Resources } from "./locales/en";

declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: "translation";
    resources: { translation: Resources };
  }
}
