import { en } from "./catalogs/en.js";
import { zhCN } from "./catalogs/zh-CN.js";
import type { MessageCatalog } from "./messageCatalog.js";

export interface LocaleDefinition {
  readonly nativeLabel: string;
  readonly aliases?: readonly string[];
  readonly dateTimeLocale?: string;
  readonly numberLocale?: string;
  readonly direction?: "ltr" | "rtl";
  readonly messages?: MessageCatalog;
  readonly loadMessages?: () => Promise<MessageCatalog>;
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
    loadMessages: () => import("./catalogs/es.js").then((module) => module.es),
  },
  fr: {
    nativeLabel: "Français",
    dateTimeLocale: "fr-FR",
    numberLocale: "fr-FR",
    direction: "ltr",
    loadMessages: () => import("./catalogs/fr.js").then((module) => module.fr),
  },
  ja: {
    nativeLabel: "日本語",
    aliases: ["ja-JP"],
    dateTimeLocale: "ja-JP",
    numberLocale: "ja-JP",
    direction: "ltr",
    loadMessages: () => import("./catalogs/ja.js").then((module) => module.ja),
  },
  ko: {
    nativeLabel: "한국어",
    dateTimeLocale: "ko-KR",
    numberLocale: "ko-KR",
    direction: "ltr",
    loadMessages: () => import("./catalogs/ko.js").then((module) => module.ko),
  },
  "pt-BR": {
    nativeLabel: "Português (Brasil)",
    dateTimeLocale: "pt-BR",
    numberLocale: "pt-BR",
    direction: "ltr",
    loadMessages: () => import("./catalogs/pt-BR.js").then((module) => module.ptBR),
  },
  ru: {
    nativeLabel: "Русский",
    aliases: ["ru-RU"],
    dateTimeLocale: "ru-RU",
    numberLocale: "ru-RU",
    direction: "ltr",
    loadMessages: () => import("./catalogs/ru.js").then((module) => module.ru),
  },
  "zh-TW": {
    nativeLabel: "繁體中文",
    aliases: ["zh-Hant-TW"],
    dateTimeLocale: "zh-TW",
    numberLocale: "zh-TW",
    direction: "ltr",
    loadMessages: () => import("./catalogs/zh-TW.js").then((module) => module.zhTW),
  },
  de: {
    nativeLabel: "Deutsch",
    dateTimeLocale: "de-DE",
    numberLocale: "de-DE",
    direction: "ltr",
    loadMessages: () => import("./catalogs/de.js").then((module) => module.de),
  },
  it: {
    nativeLabel: "Italiano",
    dateTimeLocale: "it-IT",
    numberLocale: "it-IT",
    direction: "ltr",
    loadMessages: () => import("./catalogs/it.js").then((module) => module.it),
  },
  id: {
    nativeLabel: "Bahasa Indonesia",
    dateTimeLocale: "id-ID",
    numberLocale: "id-ID",
    direction: "ltr",
    loadMessages: () => import("./catalogs/id.js").then((module) => module.id),
  },
  tr: {
    nativeLabel: "Türkçe",
    dateTimeLocale: "tr-TR",
    numberLocale: "tr-TR",
    direction: "ltr",
    loadMessages: () => import("./catalogs/tr.js").then((module) => module.tr),
  },
  vi: {
    nativeLabel: "Tiếng Việt",
    dateTimeLocale: "vi-VN",
    numberLocale: "vi-VN",
    direction: "ltr",
    loadMessages: () => import("./catalogs/vi.js").then((module) => module.vi),
  },
  pl: {
    nativeLabel: "Polski",
    dateTimeLocale: "pl-PL",
    numberLocale: "pl-PL",
    direction: "ltr",
    loadMessages: () => import("./catalogs/pl.js").then((module) => module.pl),
  },
  th: {
    nativeLabel: "ไทย",
    dateTimeLocale: "th-TH",
    numberLocale: "th-TH",
    direction: "ltr",
    loadMessages: () => import("./catalogs/th.js").then((module) => module.th),
  },
  nl: {
    nativeLabel: "Nederlands",
    dateTimeLocale: "nl-NL",
    numberLocale: "nl-NL",
    direction: "ltr",
    loadMessages: () => import("./catalogs/nl.js").then((module) => module.nl),
  },
  uk: {
    nativeLabel: "Українська",
    dateTimeLocale: "uk-UA",
    numberLocale: "uk-UA",
    direction: "ltr",
    loadMessages: () => import("./catalogs/uk.js").then((module) => module.uk),
  },
  hi: {
    nativeLabel: "हिन्दी",
    dateTimeLocale: "hi-IN",
    numberLocale: "hi-IN",
    direction: "ltr",
    loadMessages: () => import("./catalogs/hi.js").then((module) => module.hi),
  },
  ar: {
    nativeLabel: "العربية",
    dateTimeLocale: "ar",
    numberLocale: "ar",
    direction: "rtl",
    loadMessages: () => import("./catalogs/ar.js").then((module) => module.ar),
  },
  he: {
    nativeLabel: "עברית",
    dateTimeLocale: "he-IL",
    numberLocale: "he-IL",
    direction: "rtl",
    loadMessages: () => import("./catalogs/he.js").then((module) => module.he),
  },
  ms: {
    nativeLabel: "Bahasa Melayu",
    dateTimeLocale: "ms-MY",
    numberLocale: "ms-MY",
    direction: "ltr",
    loadMessages: () => import("./catalogs/ms.js").then((module) => module.ms),
  },
  cs: {
    nativeLabel: "Čeština",
    dateTimeLocale: "cs-CZ",
    numberLocale: "cs-CZ",
    direction: "ltr",
    loadMessages: () => import("./catalogs/cs.js").then((module) => module.cs),
  },
  ro: {
    nativeLabel: "Română",
    dateTimeLocale: "ro-RO",
    numberLocale: "ro-RO",
    direction: "ltr",
    loadMessages: () => import("./catalogs/ro.js").then((module) => module.ro),
  },
  hu: {
    nativeLabel: "Magyar",
    dateTimeLocale: "hu-HU",
    numberLocale: "hu-HU",
    direction: "ltr",
    loadMessages: () => import("./catalogs/hu.js").then((module) => module.hu),
  },
  sv: {
    nativeLabel: "Svenska",
    dateTimeLocale: "sv-SE",
    numberLocale: "sv-SE",
    direction: "ltr",
    loadMessages: () => import("./catalogs/sv.js").then((module) => module.sv),
  },
  "pt-PT": {
    nativeLabel: "Português (Portugal)",
    dateTimeLocale: "pt-PT",
    numberLocale: "pt-PT",
    direction: "ltr",
    loadMessages: () => import("./catalogs/pt-PT.js").then((module) => module.ptPT),
  },
  "zh-HK": {
    nativeLabel: "繁體中文（香港）",
    dateTimeLocale: "zh-HK",
    numberLocale: "zh-HK",
    direction: "ltr",
    loadMessages: () => import("./catalogs/zh-HK.js").then((module) => module.zhHK),
  },
  "zh-MO": {
    nativeLabel: "繁體中文（澳門）",
    dateTimeLocale: "zh-MO",
    numberLocale: "zh-MO",
    direction: "ltr",
    loadMessages: () => import("./catalogs/zh-MO.js").then((module) => module.zhMO),
  },
  "zh-Hant": {
    nativeLabel: "繁體中文（通用）",
    dateTimeLocale: "zh-Hant",
    numberLocale: "zh-Hant",
    direction: "ltr",
    loadMessages: () => import("./catalogs/zh-Hant.js").then((module) => module.zhHant),
  },
} as const satisfies Readonly<Record<string, LocaleDefinition>>;

export type LocaleId = keyof typeof LOCALE_REGISTRY;
export const DEFAULT_LOCALE: LocaleId = "zh-CN";
export const LOCALES: readonly LocaleId[] = Object.freeze(Object.keys(LOCALE_REGISTRY) as LocaleId[]);
export const LOCALE_OPTIONS = Object.freeze(LOCALES.map((id) => ({
  id,
  nativeLabel: LOCALE_REGISTRY[id].nativeLabel,
})));

const loaded = new Map<LocaleId, MessageCatalog>();
const loading = new Map<LocaleId, Promise<MessageCatalog>>();
for (const locale of LOCALES) {
  const definition: LocaleDefinition = LOCALE_REGISTRY[locale];
  if (definition.messages) loaded.set(locale, definition.messages);
}

export function isLocaleCatalogLoaded(locale: LocaleId): boolean {
  return loaded.has(locale);
}

export function loadLocaleCatalog(locale: LocaleId): Promise<MessageCatalog> {
  const existing = loaded.get(locale);
  if (existing) return Promise.resolve(existing);
  const pending = loading.get(locale);
  if (pending) return pending;
  const definition: LocaleDefinition = LOCALE_REGISTRY[locale];
  const operation = Promise.resolve().then(() => {
    if (!definition.loadMessages) throw new Error(`No catalog loader for ${locale}`);
    return definition.loadMessages();
  }).then((catalog) => {
    loaded.set(locale, catalog);
    return catalog;
  }).finally(() => { loading.delete(locale); });
  loading.set(locale, operation);
  return operation;
}

const definitions = Object.fromEntries(LOCALES.map((locale) => [locale, {
  ...LOCALE_REGISTRY[locale],
  get messages(): MessageCatalog {
    const catalog = loaded.get(locale);
    if (!catalog) throw new Error(`Load locale ${locale} before reading its messages`);
    return catalog;
  },
}])) as Record<LocaleId, LocaleDefinition & { readonly messages: MessageCatalog }>;

export function localeDefinition(locale: LocaleId): LocaleDefinition & { readonly messages: MessageCatalog } {
  return definitions[locale];
}
