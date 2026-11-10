import { StrategyRunStreamError } from "../backtestRunStream.js";
import { resultKinds, type CommittedIdentity, type ContinuousPage, type ResultKind } from "./continuousTypes.js";

export type ContinuousView = Omit<ContinuousPage, "items" | "more" | "next_cursor">;
type Row = { value: unknown; bytes: number };
type Rows = Record<ResultKind, Map<number, Row>>;
const tables = (): Rows => Object.fromEntries(resultKinds.map((kind) => [kind, new Map()])) as Rows;
const fields = ["id", "generation", "revision", "checkpoint_revision", "sequence", "event_time_ms", "data_revision"] as const;
export function sameCommit(a: CommittedIdentity, b: CommittedIdentity): boolean { return fields.every((field) => a[field] === b[field]); }
function invalid(): never { throw new StrategyRunStreamError("CONTINUOUS_VIEW_INVALID", "Incomplete or inconsistent committed strategy view"); }
function count(value: unknown): value is number { return Number.isSafeInteger(value) && Number(value) >= 0; }
function freeze(value: unknown): void {
  if (value === null || typeof value !== "object" || Object.isFrozen(value)) return;
  Object.freeze(value);
  for (const item of Object.values(value)) freeze(item);
}

/** Stage only changed rows. Publish a complete group synchronously; retain the
 * previous committed view through resets, reconnects and rejected partial groups. */
export class ContinuousViewReducer {
  current: ContinuousView | null = null;
  private committed = tables();
  private bytes = 0;
  private group: { snapshot: boolean; page: ContinuousPage; rows: Rows; bytes: number } | null = null;

  constructor(readonly runId: string, readonly maxBytes = 16 * 1024 * 1024) {}

  reset(): void { this.group = null; }

  accept(page: ContinuousPage, options: { snapshot: boolean; begin: boolean; complete: boolean; after: number }): ContinuousView | null {
    const point = page.identity;
    if (!point || point.id !== this.runId || typeof point.data_revision !== "string" || !point.data_revision
      || ![point.generation, point.revision, point.checkpoint_revision].every((value) => count(value) && value >= 1)
      || !count(point.sequence) || !count(point.event_time_ms) || !sameCommit(point, page.run)
      || !Array.isArray(page.items) || page.items.length > 200 || typeof page.more !== "boolean" || page.more === options.complete
      || !page.counts || !resultKinds.every((kind) => count(page.counts[kind])) || typeof page.stale !== "boolean") invalid();
    if (options.begin) {
      if (!options.snapshot && (!this.current || options.after !== this.current.identity.checkpoint_revision
        || point.generation !== this.current.identity.generation || point.data_revision !== this.current.identity.data_revision)) invalid();
      if (this.current && (point.generation < this.current.identity.generation
        || (point.generation === this.current.identity.generation
          && (point.checkpoint_revision < this.current.identity.checkpoint_revision || point.revision < this.current.identity.revision)))) invalid();
      this.group = { snapshot: options.snapshot, page, rows: tables(), bytes: 0 };
    }
    const group = this.group;
    if (!group || group.snapshot !== options.snapshot || !sameCommit(group.page.identity, point)
      || resultKinds.some((kind) => group.page.counts[kind] !== page.counts[kind])) invalid();
    for (const item of page.items) {
      if (!resultKinds.includes(item.kind) || !count(item.index) || item.index >= page.counts[item.kind]
        || group.rows[item.kind].has(item.index)) invalid();
      const bytes = new TextEncoder().encode(JSON.stringify(item.value)).byteLength + 256;
      group.bytes += bytes;
      if (this.bytes + group.bytes > this.maxBytes) {
        this.reset();
        throw new StrategyRunStreamError("BUDGET_EXCEEDED", "Strategy view capacity reached; saved execution continues");
      }
      freeze(item.value); group.rows[item.kind].set(item.index, { value: item.value, bytes });
    }
    if (!options.complete) return null;
    for (const kind of resultKinds) {
      let total = group.snapshot ? 0 : this.committed[kind].size;
      for (const index of group.rows[kind].keys()) if (group.snapshot || !this.committed[kind].has(index)) total += 1;
      if (total !== page.counts[kind]) invalid();
    }
    if (group.snapshot) { this.committed = group.rows; this.bytes = group.bytes; }
    else for (const kind of resultKinds) for (const [index, row] of group.rows[kind]) {
      this.bytes += row.bytes - (this.committed[kind].get(index)?.bytes ?? 0);
      this.committed[kind].set(index, row);
    }
    const view: ContinuousView = { run: page.run, identity: point, counts: page.counts, summary: page.summary, stale: page.stale };
    freeze(view);
    this.current = view; this.group = null;
    return view;
  }

  rows(kind: ResultKind, identity: CommittedIdentity, limit = 100): unknown[] {
    if (!this.current || !sameCommit(identity, this.current.identity)) invalid();
    const values: unknown[] = [], length = this.current.counts[kind];
    for (let index = Math.max(0, length - Math.min(200, Math.max(0, limit))); index < length; index += 1)
      values.push(this.committed[kind].get(index)!.value);
    return values;
  }

  diagnostics() { return { bytes: this.bytes, pendingBytes: this.group?.bytes ?? 0, committed: this.current?.identity ?? null }; }
  clear(): void { this.current = null; this.committed = tables(); this.bytes = 0; this.reset(); }
}
