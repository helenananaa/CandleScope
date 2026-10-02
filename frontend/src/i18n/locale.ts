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
