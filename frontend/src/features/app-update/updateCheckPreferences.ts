import { getBrowserStorage, type StorageLike } from "../../shared/browserStorage.js";

const STORAGE_KEY = "candlescope-update-check";
/** Enough for every version anyone skips; the oldest give way. */
const MAX_SKIPPED_VERSIONS = 20;

export interface UpdateCheckPreferences {
  /** "Check for updates" in Settings; on unless turned off. */
  readonly enabled: boolean;
  /** Versions whose notice the user chose to skip. */
  readonly skippedVersions: readonly string[];
}

const DEFAULTS: UpdateCheckPreferences = Object.freeze({ enabled: true, skippedVersions: Object.freeze([]) });

function parse(raw: string | null): UpdateCheckPreferences {
  if (!raw) return DEFAULTS;
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value !== "object" || value === null) return DEFAULTS;
    const record = value as Record<string, unknown>;
    const skipped = Array.isArray(record.skippedVersions)
      ? record.skippedVersions.filter((item): item is string => typeof item === "string" && item.length <= 32)
      : [];
    return { enabled: record.enabled !== false, skippedVersions: skipped.slice(-MAX_SKIPPED_VERSIONS) };
  } catch {
    return DEFAULTS;
  }
}

export interface UpdateCheckPreferencesStore {
  get(): UpdateCheckPreferences;
  setEnabled(enabled: boolean): void;
  skipVersion(version: string): void;
  subscribe(listener: () => void): () => void;
}

/** Saved in this profile's browser storage; when storage is unavailable, kept for this session only. */
export function createUpdateCheckPreferences(storage: () => StorageLike | null = getBrowserStorage): UpdateCheckPreferencesStore {
  let current: UpdateCheckPreferences | null = null;
  const listeners = new Set<() => void>();
  const read = (): UpdateCheckPreferences => {
    if (current) return current;
    let raw: string | null = null;
    try { raw = storage()?.getItem(STORAGE_KEY) ?? null; } catch { /* storage blocked */ }
    current = parse(raw);
    return current;
  };
  const write = (next: UpdateCheckPreferences) => {
    current = next;
    try { storage()?.setItem(STORAGE_KEY, JSON.stringify(next)); } catch { /* kept in memory */ }
    for (const listener of [...listeners]) listener();
  };
  return {
    get: read,
    setEnabled(enabled) {
      const before = read();
      if (before.enabled !== enabled) write({ ...before, enabled });
    },
    skipVersion(version) {
      const before = read();
      if (before.skippedVersions.includes(version)) return;
      write({ ...before, skippedVersions: [...before.skippedVersions, version].slice(-MAX_SKIPPED_VERSIONS) });
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
  };
}

export const updateCheckPreferences = createUpdateCheckPreferences();
