export interface ContinuousRunSettings {
  from: string; balance: string; percent: string; fee: string; slippage: string; output: "SIGNAL" | "TARGET_POSITION" | "ORDER_INTENT";
  /** The account's leverage on the practice account model (ADR-BACKTEST-015 P6e); absent on older references. */
  leverage?: string;
}
export interface ContinuousRunReference { schema: 1; requestKey: string; runId: string | null; inputRevision: string; settings: ContinuousRunSettings; createdAtMs: number; }
const PREFIX = "candlescope.continuous-run.v1:";
export function continuousReferenceKey(scope: string): string { return PREFIX + scope; }
export function readContinuousReference(storage: Pick<Storage, "getItem">, scope: string): ContinuousRunReference | null {
  const raw = storage.getItem(continuousReferenceKey(scope));
  if (raw === null) return null;
  if (raw.length > 2048) throw new Error("CONTINUOUS_REFERENCE_INVALID");
  return parseContinuousReference(JSON.parse(raw));
}
/** Validate a stored reference, from browser storage or the backend. Throws CONTINUOUS_REFERENCE_INVALID. */
export function parseContinuousReference(raw: unknown): ContinuousRunReference {
  const value = raw as ContinuousRunReference;
  if (!value || typeof value !== "object" || value.schema !== 1 || typeof value.requestKey !== "string" || !value.requestKey || value.requestKey.length > 128
    || (value.runId !== null && (typeof value.runId !== "string" || !value.runId || value.runId.length > 128))
    || typeof value.inputRevision !== "string" || value.inputRevision.length > 512 || !Number.isSafeInteger(value.createdAtMs) || value.createdAtMs < 0
    || !value.settings || !["from", "balance", "percent", "fee", "slippage"].every((key) => {
      const item = value.settings[key as keyof ContinuousRunSettings]; return typeof item === "string" && item.length <= 64;
    }) || !["SIGNAL", "TARGET_POSITION", "ORDER_INTENT"].includes(value.settings.output)
    || (value.settings.leverage !== undefined && (typeof value.settings.leverage !== "string" || value.settings.leverage.length > 64))) throw new Error("CONTINUOUS_REFERENCE_INVALID");
  return value;
}
export function saveContinuousReference(storage: Storage, scope: string, value: ContinuousRunReference): void {
  const key = continuousReferenceKey(scope);
  if (storage.getItem(key) === null) {
    let count = 0;
    for (let index = 0; index < storage.length; index += 1) if (storage.key(index)?.startsWith(PREFIX)) count += 1;
    if (count >= 64) throw new Error("CONTINUOUS_REFERENCE_CAPACITY");
  }
  storage.setItem(key, JSON.stringify(value));
}
export function continuousArchiveScope(scope: string, key: string): string { return scope + "::" + key; }
export function activateContinuousReference(storage: Storage, scope: string, value: ContinuousRunReference): void {
  // Archive each request before changing the selected pointer. Concurrent views
  // may choose different runs, but cannot discard one another's recovery keys.
  saveContinuousReference(storage, continuousArchiveScope(scope, value.requestKey), value);
  saveContinuousReference(storage, scope, value);
}
export function listContinuousReferences(storage: Storage, scope: string): ContinuousRunReference[] {
  const values = new Map<string, ContinuousRunReference>(), prefix = continuousReferenceKey(scope) + "::";
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    if (key?.startsWith(prefix)) {
      const value = readContinuousReference(storage, key.slice(PREFIX.length));
      if (value) values.set(value.requestKey, value);
    }
  }
  const current = readContinuousReference(storage, scope);
  if (current) values.set(current.requestKey, current);
  return [...values.values()].sort((a, b) => b.createdAtMs - a.createdAtMs);
}

// -- ADR-BACKTEST-015 P3c: references live in the backend -------------------------

/** Set in browser storage once its references are in the backend. It must not start with the reference prefix. */
export const CONTINUOUS_REFERENCE_IMPORT_MARKER = "candlescope.continuous-run.imported-to-backend.v1";
const KIND = "continuous-run";
const IMPORT_BATCH = 512;

export interface ContinuousReferenceStore {
  read(scope: string): Promise<ContinuousRunReference | null>;
  list(scope: string): Promise<ContinuousRunReference[]>;
  /** Archive a request, then select it for the scope. */
  activate(scope: string, value: ContinuousRunReference): Promise<void>;
  /** Archive a request without selecting it. */
  archive(scope: string, value: ContinuousRunReference): Promise<void>;
}

interface ReferenceManager {
  loadStrategyReference(kind: typeof KIND, key: string): Promise<unknown>;
  listStrategyReferences(kind: typeof KIND, prefix?: string): Promise<Array<{ key: string; value: unknown }>>;
  saveStrategyReference(kind: typeof KIND, key: string, value: unknown): Promise<void>;
  importStrategyReferences(kind: typeof KIND, entries: Array<{ key: string; value: unknown }>): Promise<unknown>;
}

function valid(value: unknown): ContinuousRunReference | null {
  try { return parseContinuousReference(value); } catch { return null; }
}

/**
 * A chart's forward-run references in the backend, where a new origin or a changed desktop
 * UI port still finds them. Browser-storage references are imported once and kept; until
 * that import succeeds they stay readable from browser storage.
 */
export function backendContinuousReferences(manager: ReferenceManager, legacy: Storage | null): ContinuousReferenceStore {
  let importing: Promise<boolean> | null = null;
  const imported = (): Promise<boolean> => {
    if (!legacy || legacy.getItem(CONTINUOUS_REFERENCE_IMPORT_MARKER) !== null) return Promise.resolve(true);
    importing ??= (async () => {
      try {
        const entries: Array<{ key: string; value: ContinuousRunReference }> = [];
        for (let index = 0; index < legacy.length; index += 1) {
          const key = legacy.key(index);
          if (!key?.startsWith(PREFIX)) continue;
          const value = valid(JSON.parse(legacy.getItem(key) ?? "null"));
          if (value) entries.push({ key: key.slice(PREFIX.length), value });
        }
        for (let start = 0; start < entries.length; start += IMPORT_BATCH) {
          await manager.importStrategyReferences(KIND, entries.slice(start, start + IMPORT_BATCH));
        }
        legacy.setItem(CONTINUOUS_REFERENCE_IMPORT_MARKER, JSON.stringify({ at: Date.now(), references: entries.length }));
        return true;
      } catch {
        importing = null;  // try again on the next use
        return false;
      }
    })();
    return importing;
  };
  const archiveKey = (scope: string, value: ContinuousRunReference) => continuousArchiveScope(scope, value.requestKey);
  return {
    async read(scope) {
      const done = await imported();
      const value = valid(await manager.loadStrategyReference(KIND, scope));
      if (value || done || !legacy) return value;
      return readContinuousReference(legacy, scope);
    },
    async list(scope) {
      const done = await imported();
      const values = new Map<string, ContinuousRunReference>();
      if (!done && legacy) for (const value of listContinuousReferences(legacy, scope)) values.set(value.requestKey, value);
      for (const entry of await manager.listStrategyReferences(KIND, `${scope}::`)) {
        const value = valid(entry.value);
        if (value) values.set(value.requestKey, value);
      }
      const current = await this.read(scope);
      if (current) values.set(current.requestKey, current);
      return [...values.values()].sort((a, b) => b.createdAtMs - a.createdAtMs);
    },
    async activate(scope, value) {
      await imported();
      // Archive before changing the selected pointer, as browser storage did.
      await manager.saveStrategyReference(KIND, archiveKey(scope, value), value);
      await manager.saveStrategyReference(KIND, scope, value);
    },
    async archive(scope, value) {
      await imported();
      await manager.saveStrategyReference(KIND, archiveKey(scope, value), value);
    },
  };
}
