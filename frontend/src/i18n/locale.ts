import { DEFAULT_LOCALE, LOCALES, isLocaleCatalogLoaded, loadLocaleCatalog, localeDefinition, type LocaleId } from "./registry.js";
import { resolveLocale } from "./localeResolution.js";

export { DEFAULT_LOCALE, LOCALES, LOCALE_OPTIONS, type LocaleId } from "./registry.js";

const registrations = LOCALES.map((id) => ({ id, aliases: localeDefinition(id).aliases ?? [] }));

const listeners = new Set<() => void>();
let current: LocaleId = DEFAULT_LOCALE;
let requestSequence = 0;

export function isLocaleId(value: unknown): value is LocaleId {
  return typeof value === "string" && LOCALES.some((locale) => locale === value);
}

export function normalizeLocale(value: unknown): LocaleId {
  return resolveLocale(value, registrations) ?? DEFAULT_LOCALE;
}

/** The system's preferred languages, most preferred first; empty where no browser is available. */
export function systemLanguages(): readonly string[] {
  if (typeof navigator === "undefined") return [];
  if (Array.isArray(navigator.languages) && navigator.languages.length > 0) return navigator.languages;
  return typeof navigator.language === "string" && navigator.language ? [navigator.language] : [];
}

/**
 * The first supported language among the system's preferences, matched like saved values
 * (parents and aliases); undefined when none is supported.
 */
export function detectSystemLocale(languages: readonly string[] = systemLanguages()): LocaleId | undefined {
  for (const language of languages) {
    const locale = resolveLocale(language, registrations);
    if (locale) return locale;
  }
  return undefined;
}

function applyDocumentLang(locale: LocaleId): void {
  if (typeof document === "undefined") return;
  document.documentElement.lang = locale;
  document.documentElement.dir = localeDefinition(locale).direction ?? "ltr";
}

export function getLocale(): LocaleId {
  return current;
}

export function setLocale(value: unknown): LocaleId {
  const locale = normalizeLocale(value);
  if (!isLocaleCatalogLoaded(locale)) throw new Error(`Use setLocaleAsync to load locale ${locale}`);
  requestSequence += 1;
  const changed = locale !== current;
  current = locale;
  applyDocumentLang(locale);
  if (changed) {
    for (const listener of listeners) listener();
  }
  return locale;
}

/** Publish language, direction and notifications together, only after loading. */
export async function setLocaleAsync(value: unknown): Promise<LocaleId> {
  const locale = normalizeLocale(value);
  const request = ++requestSequence;
  await loadLocaleCatalog(locale);
  return request === requestSequence ? setLocale(locale) : current;
}

/** Keep the startup surface usable if an optional language asset is unavailable. */
export async function initializeLocale(value: unknown): Promise<LocaleId> {
  if (normalizeLocale(value) === current) {
    applyDocumentLang(current);
    return current;
  }
  try {
    return await setLocaleAsync(value);
  } catch (error) {
    console.warn("Locale catalog could not be loaded; retaining the current language", error);
    return current;
  }
}

export function hydrateLocale(value: unknown): LocaleId {
  return setLocale(value);
}

export function subscribeLocale(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
