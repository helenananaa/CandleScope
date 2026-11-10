import type { ContinuousRepairConfirm } from "./continuousTypes.js";

const KEY = "candlescope.continuous-repair-intents.v1";
const MAX_BYTES = 65536, MAX_PENDING = 16;
export interface ContinuousRepairIntent {
  schema: 1; runId: string; requestKey: string; body: ContinuousRepairConfirm; createdAtMs: number;
}
type Reader = Pick<Storage, "getItem">;
type Writer = Pick<Storage, "getItem" | "setItem">;
function invalid(): never { throw new Error("Invalid saved repair request; existing data retained"); }
function text(value: unknown, limit: number): value is string { return typeof value === "string" && value.length > 0 && value.length <= limit; }
function count(value: unknown): value is number { return Number.isSafeInteger(value) && Number(value) >= 0; }
function valid(value: ContinuousRepairIntent): boolean {
  const body = value?.body, point = body?.expected;
  return value?.schema === 1 && text(value.runId, 128) && text(value.requestKey, 128) && count(value.createdAtMs)
    && body?.confirmed === true && typeof body.resume_after === "boolean" && text(body.plan_id, 64) && /^[0-9a-f]{64}$/.test(body.plan_id)
    && point?.id === value.runId && text(point.data_revision, 256)
    && [point.generation, point.revision, point.checkpoint_revision].every((number) => count(number) && number > 0)
    && count(point.sequence) && count(point.event_time_ms)
    && Object.keys(value).sort().join() === "body,createdAtMs,requestKey,runId,schema"
    && Object.keys(body).sort().join() === "confirmed,expected,plan_id,resume_after"
    && Object.keys(point).sort().join() === "checkpoint_revision,data_revision,event_time_ms,generation,id,revision,sequence";
}
function read(storage: Reader): ContinuousRepairIntent[] {
  const raw = storage.getItem(KEY);
  if (raw === null) return [];
  if (new TextEncoder().encode(raw).byteLength > MAX_BYTES) invalid();
  const values: unknown = JSON.parse(raw);
  if (!Array.isArray(values) || values.length > MAX_PENDING || !values.every((value) => valid(value as ContinuousRepairIntent))) invalid();
  const rows = values as ContinuousRepairIntent[];
  if (new Set(rows.map((row) => row.runId)).size !== rows.length) invalid();
  return rows;
}
function write(storage: Writer, rows: ContinuousRepairIntent[]): void {
  const wire = JSON.stringify(rows);
  if (rows.length > MAX_PENDING || new TextEncoder().encode(wire).byteLength > MAX_BYTES) invalid();
  storage.setItem(KEY, wire);
}
export function readContinuousRepairIntent(storage: Reader, runId: string): ContinuousRepairIntent | null {
  return read(storage).find((row) => row.runId === runId) ?? null;
}
/** Save consent before POST. Mounting/recovering a reference never submits it. */
export function saveContinuousRepairIntent(storage: Writer, intent: ContinuousRepairIntent): void {
  if (!valid(intent)) invalid();
  const rows = read(storage), prior = rows.find((row) => row.runId === intent.runId);
  if (prior && prior.requestKey !== intent.requestKey) throw new Error("Recover the saved repair request before confirming another");
  write(storage, [...rows.filter((row) => row.runId !== intent.runId), intent]);
}
/** A server acknowledgement resolves only this request, never sibling data. */
export function acknowledgeContinuousRepairIntent(storage: Writer, runId: string, requestKey: string): void {
  const rows = read(storage);
  write(storage, rows.filter((row) => row.runId !== runId || row.requestKey !== requestKey));
}
