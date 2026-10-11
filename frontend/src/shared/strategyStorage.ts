export interface StrategyStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void | Promise<void>;
}

/** Desktop strategy state belongs to the app profile, including when its UI port changes. */
export function getStrategyStorage(): StrategyStorage | null {
  if (typeof window === "undefined") return null;
  let legacy: Storage | null = null;
  try { legacy = window.localStorage; } catch { /* Embedded browser may disallow storage. */ }
  const native = window.candlescopeDesktop?.strategyStorage;
  if (!native) return legacy;
  return {
    getItem(key) {
      const value = native.getItem(key);
      if (value !== null) return value;
      // First launch after an upgrade: preserve drafts from the current legacy origin.
      const previous = legacy?.getItem(key) ?? null;
      if (previous !== null) void native.setItem(key, previous).catch(() => {});
      return previous;
    },
    setItem: (key, value) => native.setItem(key, value),
  };
}
