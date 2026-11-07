import { StrategyRunStreamError } from "../backtestRunStream.js";
import type { ContinuousRepair } from "./continuousTypes.js";

const phases = ["REQUESTED", "PREPARING", "READY", "COMMITTED", "FAILED", "CANCELLED"] as const;
const terminal = (phase: ContinuousRepair["phase"]) => ["COMMITTED", "FAILED", "CANCELLED"].includes(phase);
const count = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) >= 0;
function invalid(): never { throw new StrategyRunStreamError("CONTINUOUS_VIEW_INVALID", "Invalid history repair state"); }
function freeze(value: unknown): void {
  if (value === null || typeof value !== "object" || Object.isFrozen(value)) return;
  Object.freeze(value);
  for (const item of Object.values(value)) freeze(item);
}

/** Repair metadata never replaces the committed financial result. In-flight
 * HTTP responses cannot rewind newer socket progress or terminal consent. */
export function mergeRepair(current: ContinuousRepair | null, incoming: ContinuousRepair | null | undefined, runId: string): ContinuousRepair | null {
  if (incoming == null) return current;
  const base = incoming.base_identity;
  if (!base || incoming.run_id !== runId || base.id !== runId || !phases.includes(incoming.phase)
    || typeof incoming.id !== "string" || !incoming.id || typeof incoming.request_key !== "string" || !incoming.request_key
    || ![incoming.target_revision, incoming.updated_at_ms, incoming.anchor_sequence, incoming.from_ms,
      incoming.through_ms, incoming.original_from_ms, base.generation, base.revision, base.checkpoint_revision,
      base.sequence, base.event_time_ms].every(count) || !base.generation || !base.revision || !base.checkpoint_revision
    || typeof base.data_revision !== "string" || !base.data_revision || !incoming.target_revision
    || incoming.original_from_ms > incoming.from_ms || incoming.from_ms > incoming.through_ms + 1
    || (incoming.through_ms + 1) % 60000 || incoming.from_ms % 60000 || incoming.original_from_ms % 60000
    || typeof incoming.resume_after !== "boolean" || typeof incoming.full_reinitialization !== "boolean"
    || (incoming.progress?.sequence !== undefined && !count(incoming.progress.sequence))) invalid();
  if (current) {
    if (incoming.target_revision < current.target_revision) return current;
    if (incoming.target_revision === current.target_revision && incoming.id !== current.id) invalid();
    if (incoming.id === current.id) {
      if (terminal(current.phase) && incoming.phase !== current.phase) return current;
      if (current.phase === "READY" && ["REQUESTED", "PREPARING"].includes(incoming.phase)) return current;
      if (current.phase === incoming.phase) {
        const oldSequence = current.progress?.sequence, newSequence = incoming.progress?.sequence;
        if (oldSequence !== undefined && (newSequence === undefined || newSequence < oldSequence)) return current;
        if (incoming.updated_at_ms < current.updated_at_ms && (newSequence ?? 0) <= (oldSequence ?? 0)) return current;
      }
    }
  }
  const wire = JSON.stringify(incoming);
  if (new TextEncoder().encode(wire).byteLength > 16384) invalid();
  const result = JSON.parse(wire) as ContinuousRepair;
  freeze(result);
  return result;
}

export function repairProgress(repair: ContinuousRepair): { done: number; total: number } {
  const total = Math.max(0, (repair.through_ms + 1 - repair.original_from_ms) / 60000 - repair.anchor_sequence);
  const done = repair.phase === "COMMITTED" ? total
    : Math.max(0, Math.min(total, (repair.progress?.sequence ?? repair.anchor_sequence) - repair.anchor_sequence));
  return { done, total };
}
