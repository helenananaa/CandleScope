const STORAGE_KEY = "candlescope-symbol-sources-v1";

export interface SourcePreferences { favorites: string[]; recent: string[] }

export function loadSourcePreferences(): SourcePreferences {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    const value = parsed && typeof parsed === "object" ? parsed as Record<string, unknown> : {};
    const strings = (items: unknown): string[] => Array.isArray(items)
      ? [...new Set(items.filter((item): item is string => typeof item === "string" && !!item))].slice(0, 50)
      : [];
    return { favorites: strings(value?.favorites), recent: strings(value?.recent).slice(0, 5) };
  } catch { return { favorites: [], recent: [] }; }
}

export function saveSourcePreferences(value: SourcePreferences): void {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(value)); } catch { /* Optional preferences. */ }
}

const RECENT_SYMBOLS_KEY = "candlescope-recent-symbols-v1";
export function loadRecentSymbols(): string[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(RECENT_SYMBOLS_KEY) || "[]");
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string").slice(0, 30) : [];
  } catch { return []; }
}
export function rememberRecentSymbol(key: string): void {
  try { localStorage.setItem(RECENT_SYMBOLS_KEY, JSON.stringify([key, ...loadRecentSymbols().filter((item) => item !== key)].slice(0, 30))); } catch { /* Optional preferences. */ }
}
