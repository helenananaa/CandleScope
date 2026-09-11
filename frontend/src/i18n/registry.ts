import { ar } from "./catalogs/ar.js";
import { cs } from "./catalogs/cs.js";
import { en } from "./catalogs/en.js";
import { es } from "./catalogs/es.js";
import { fr } from "./catalogs/fr.js";
import { he } from "./catalogs/he.js";
import { hi } from "./catalogs/hi.js";
import { hu } from "./catalogs/hu.js";
import { ja } from "./catalogs/ja.js";
import { ko } from "./catalogs/ko.js";
import { ms } from "./catalogs/ms.js";
import { nl } from "./catalogs/nl.js";
import { ptBR } from "./catalogs/pt-BR.js";
import { ptPT } from "./catalogs/pt-PT.js";
import { ro } from "./catalogs/ro.js";
import { ru } from "./catalogs/ru.js";
import { sv } from "./catalogs/sv.js";
import { th } from "./catalogs/th.js";
import { uk } from "./catalogs/uk.js";
import { zhCN } from "./catalogs/zh-CN.js";
import { zhHant } from "./catalogs/zh-Hant.js";
import { zhHK } from "./catalogs/zh-HK.js";
import { zhMO } from "./catalogs/zh-MO.js";
import { zhTW } from "./catalogs/zh-TW.js";
import type { MessageCatalog } from "./messageCatalog.js";

export interface LocaleDefinition {
  readonly nativeLabel: string;
  readonly aliases?: readonly string[];
  readonly dateTimeLocale?: string;
  readonly numberLocale?: string;
  readonly direction?: "ltr" | "rtl";
  readonly messages: MessageCatalog;
}

/** Add a complete catalog here to register a language throughout the Host. */
export const LOCALE_REGISTRY = {
  "zh-CN": {
    nativeLabel: "简体中文",
    aliases: ["zh", "zh-Hans"],
    messages: zhCN,
  },
  en: {
    nativeLabel: "English",
    dateTimeLocale: "en-GB",
    numberLocale: "en-US",
    messages: en,
  },
  es: {
    nativeLabel: "Español",
    dateTimeLocale: "es-ES",
    numberLocale: "es-ES",
    direction: "ltr",
    messages: es,
  },
  fr: {
    nativeLabel: "Français",
    dateTimeLocale: "fr-FR",
    numberLocale: "fr-FR",
    direction: "ltr",
    messages: fr,
  },
  ja: {
    nativeLabel: "日本語",
    aliases: ["ja-JP"],
    dateTimeLocale: "ja-JP",
    numberLocale: "ja-JP",
    direction: "ltr",
    messages: ja,
  },
  ko: {
    nativeLabel: "한국어",
    dateTimeLocale: "ko-KR",
    numberLocale: "ko-KR",
    direction: "ltr",
    messages: ko,
  },
  "pt-BR": {
    nativeLabel: "Português (Brasil)",
    dateTimeLocale: "pt-BR",
    numberLocale: "pt-BR",
    direction: "ltr",
    messages: ptBR,
  },
  ru: {
    nativeLabel: "Русский",
    aliases: ["ru-RU"],
    dateTimeLocale: "ru-RU",
    numberLocale: "ru-RU",
    direction: "ltr",
    messages: ru,
  },
  "zh-TW": {
    nativeLabel: "繁體中文",
    aliases: ["zh-Hant-TW"],
    dateTimeLocale: "zh-TW",
    numberLocale: "zh-TW",
    direction: "ltr",
    messages: zhTW,
  },
  th: {
    nativeLabel: "ไทย",
    dateTimeLocale: "th-TH",
    numberLocale: "th-TH",
    direction: "ltr",
    messages: th,
  },
  nl: {
    nativeLabel: "Nederlands",
    dateTimeLocale: "nl-NL",
    numberLocale: "nl-NL",
    direction: "ltr",
    messages: nl,
  },
  uk: {
    nativeLabel: "Українська",
    dateTimeLocale: "uk-UA",
    numberLocale: "uk-UA",
    direction: "ltr",
    messages: uk,
  },
  hi: {
    nativeLabel: "हिन्दी",
    dateTimeLocale: "hi-IN",
    numberLocale: "hi-IN",
    direction: "ltr",
    messages: hi,
  },
  ar: {
    nativeLabel: "العربية",
    dateTimeLocale: "ar",
    numberLocale: "ar",
    direction: "rtl",
    messages: ar,
  },
  he: {
    nativeLabel: "עברית",
    dateTimeLocale: "he-IL",
    numberLocale: "he-IL",
    direction: "rtl",
    messages: he,
  },
  ms: {
    nativeLabel: "Bahasa Melayu",
    dateTimeLocale: "ms-MY",
    numberLocale: "ms-MY",
    direction: "ltr",
    messages: ms,
  },
  cs: {
    nativeLabel: "Čeština",
    dateTimeLocale: "cs-CZ",
    numberLocale: "cs-CZ",
    direction: "ltr",
    messages: cs,
  },
  ro: {
    nativeLabel: "Română",
    dateTimeLocale: "ro-RO",
    numberLocale: "ro-RO",
    direction: "ltr",
    messages: ro,
  },
  hu: {
    nativeLabel: "Magyar",
    dateTimeLocale: "hu-HU",
    numberLocale: "hu-HU",
    direction: "ltr",
    messages: hu,
  },
  sv: {
    nativeLabel: "Svenska",
    dateTimeLocale: "sv-SE",
    numberLocale: "sv-SE",
    direction: "ltr",
    messages: sv,
  },
  "pt-PT": {
    nativeLabel: "Português (Portugal)",
    dateTimeLocale: "pt-PT",
    numberLocale: "pt-PT",
    direction: "ltr",
    messages: ptPT,
  },
  "zh-HK": {
    nativeLabel: "繁體中文（香港）",
    dateTimeLocale: "zh-HK",
    numberLocale: "zh-HK",
    direction: "ltr",
    messages: zhHK,
  },
  "zh-MO": {
    nativeLabel: "繁體中文（澳門）",
    dateTimeLocale: "zh-MO",
    numberLocale: "zh-MO",
    direction: "ltr",
    messages: zhMO,
  },
  "zh-Hant": {
    nativeLabel: "繁體中文（通用）",
    dateTimeLocale: "zh-Hant",
    numberLocale: "zh-Hant",
    direction: "ltr",
    messages: zhHant,
  },
} as const satisfies Readonly<Record<string, LocaleDefinition>>;

export type LocaleId = keyof typeof LOCALE_REGISTRY;
export const DEFAULT_LOCALE: LocaleId = "zh-CN";
export const LOCALES: readonly LocaleId[] = Object.freeze(Object.keys(LOCALE_REGISTRY) as LocaleId[]);
export const LOCALE_OPTIONS = Object.freeze(LOCALES.map((id) => ({
  id,
  nativeLabel: LOCALE_REGISTRY[id].nativeLabel,
})));

export function localeDefinition(locale: LocaleId): LocaleDefinition {
  return LOCALE_REGISTRY[locale];
}
