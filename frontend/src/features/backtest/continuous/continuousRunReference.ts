export interface ContinuousRunSettings { from: string; balance: string; percent: string; fee: string; slippage: string; output: "SIGNAL" | "TARGET_POSITION" | "ORDER_INTENT"; }
export interface ContinuousRunReference { schema: 1; requestKey: string; runId: string | null; inputRevision: string; settings: ContinuousRunSettings; createdAtMs: number; }
const PREFIX = "candlescope.continuous-run.v1:";
export function continuousReferenceKey(scope: string): string { return PREFIX + scope; }
export function readContinuousReference(storage: Pick<Storage, "getItem">, scope: string): ContinuousRunReference | null {
  const raw = storage.getItem(continuousReferenceKey(scope));
  if (raw === null) return null;
  if (raw.length > 2048) throw new Error("CONTINUOUS_REFERENCE_INVALID");
  const value = JSON.parse(raw) as ContinuousRunReference;
  if (value.schema !== 1 || typeof value.requestKey !== "string" || !value.requestKey || value.requestKey.length > 128
    || (value.runId !== null && (typeof value.runId !== "string" || !value.runId || value.runId.length > 128))
    || typeof value.inputRevision !== "string" || value.inputRevision.length > 512 || !Number.isSafeInteger(value.createdAtMs) || value.createdAtMs < 0
    || !value.settings || !["from", "balance", "percent", "fee", "slippage"].every((key) => {
      const item = value.settings[key as keyof ContinuousRunSettings]; return typeof item === "string" && item.length <= 64;
    }) || !["SIGNAL", "TARGET_POSITION", "ORDER_INTENT"].includes(value.settings.output)) throw new Error("CONTINUOUS_REFERENCE_INVALID");
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
