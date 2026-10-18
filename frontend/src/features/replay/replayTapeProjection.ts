import { parseReplayDisplayBar } from "./replayParser.js";
import { replayHistoryRetryDelay } from "./replayHistoryRetry.js";
import type { ReplayDigest, ReplayDisplayBar } from "./replayTypes.js";
import { parseHistoryPolicy, parseIdentity, type ReplayHistoryIdentity, type ReplayHistoryPolicy } from "./replayHistoryProvider.js";

export interface ReplayTapeProjectionRequest {
  trackId: string;
  displayInterval: string;
  dataEpoch: string;
  revealedBoundaryMs: number;
  sourceSequence: number;
  limit: number;
  beforeMs?: number;
  historyEpoch?: ReplayDigest;
}
export interface ReplayTapeProjection {
  protocol: "replay.v3";
  schema_version: "replay.tape-projection.v1";
  run_id: string;
  identity: ReplayHistoryIdentity;
  history_policy: ReplayHistoryPolicy;
  history_scope: "FROZEN_WARMUP_AND_TAPE" | "CONTEXT_AND_FROZEN_TAPE";
  history_epoch: ReplayDigest;
  context_prepared_before_ms: number;
  context_target_before_ms: number;
  incomplete_context_buckets: readonly number[];
  session_id: string;
  track_id: string;
  data_epoch: ReplayDigest;
  display_interval: string;
  revealed_boundary_ms: number;
  source_sequence: number;
  target_sequence: number;
  before_ms: number | null;
  history_boundary_ms: number;
  next_before_ms: number | null;
  has_more: boolean | null;
  status: "ready" | "preparing";
  prepared_sequence: number;
  bars: readonly ReplayDisplayBar[];
}

export function parseReplayTapeProjection(value: unknown): ReplayTapeProjection {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new TypeError("invalid tape projection");
  const row = value as Record<string, unknown>;
  const fields = ["protocol", "schema_version", "run_id", "identity", "history_policy", "history_scope", "history_epoch", "context_prepared_before_ms",
    "context_target_before_ms", "incomplete_context_buckets", "session_id", "track_id", "data_epoch", "display_interval",
    "revealed_boundary_ms", "source_sequence", "target_sequence", "before_ms", "history_boundary_ms", "next_before_ms", "has_more",
    "status", "prepared_sequence", "bars"];
  if (Object.keys(row).length !== fields.length || fields.some(key => !Object.hasOwn(row, key))) throw new TypeError("incompatible tape projection fields");
  if (row.protocol !== "replay.v3" || row.schema_version !== "replay.tape-projection.v1"
    || !["FROZEN_WARMUP_AND_TAPE", "CONTEXT_AND_FROZEN_TAPE"].includes(String(row.history_scope))
    || !/^sha256:[0-9a-f]{64}$/.test(String(row.history_epoch))
    || !["ready", "preparing"].includes(String(row.status)) || !/^sha256:[0-9a-f]{64}$/.test(String(row.data_epoch))
    || [row.run_id, row.session_id, row.track_id, row.display_interval].some(item => typeof item !== "string" || !item.length)
    || [row.revealed_boundary_ms, row.source_sequence, row.prepared_sequence, row.target_sequence, row.history_boundary_ms,
      row.context_prepared_before_ms, row.context_target_before_ms]
      .some(item => !Number.isSafeInteger(item) || Number(item) < 0)
    || (row.before_ms !== null && (!Number.isSafeInteger(row.before_ms) || Number(row.before_ms) < 0 || Number(row.before_ms) > Number(row.revealed_boundary_ms) + 1))
    || Number(row.prepared_sequence) > Number(row.target_sequence) || Number(row.target_sequence) > Number(row.source_sequence)
    || Number(row.context_prepared_before_ms) > Number(row.context_target_before_ms)
    || Number(row.context_target_before_ms) > Number(row.revealed_boundary_ms) + 1
    || ((row.status === "ready") !== (row.prepared_sequence === row.target_sequence
      && row.context_prepared_before_ms === row.context_target_before_ms))) throw new TypeError("invalid tape projection state");
  if (!Array.isArray(row.incomplete_context_buckets) || row.incomplete_context_buckets.length > 500
    || (row.status === "preparing" && row.incomplete_context_buckets.length)
    || row.incomplete_context_buckets.some((at, i, all) => !Number.isSafeInteger(at) || at < Number(row.history_boundary_ms)
      || at > Number(row.revealed_boundary_ms) || (i > 0 && at <= all[i - 1]))) throw new TypeError("invalid tape context gaps");
  if (row.status === "preparing" ? row.next_before_ms !== null || row.has_more !== null
    : !Number.isSafeInteger(row.next_before_ms) || Number(row.next_before_ms) < 0 || typeof row.has_more !== "boolean"
      || (row.before_ms !== null && Number(row.next_before_ms) > Number(row.before_ms))
      || row.has_more !== (Number(row.next_before_ms) > Number(row.history_boundary_ms))
      || (row.has_more && row.before_ms !== null && Number(row.next_before_ms) >= Number(row.before_ms))) throw new TypeError("invalid tape history cursor");
  if (!Array.isArray(row.bars) || row.bars.length > 500 || (row.status === "preparing" && row.bars.length)) throw new TypeError("invalid tape projection bars");
  const bars = row.bars.map((item, i) => parseReplayDisplayBar(item, `tape projection.bars[${i}]`));
  for (let i = 0; i < bars.length; i++) {
    const bar = bars[i]!;
    if (bar.open_time_ms > Number(row.revealed_boundary_ms) || bar.last_base_open_ms > Number(row.revealed_boundary_ms)
      || (bar.is_closed && bar.close_time_ms > Number(row.revealed_boundary_ms))
      || (row.before_ms !== null && bar.open_time_ms >= Number(row.before_ms))
      || (bar.is_closed && row.incomplete_context_buckets.includes(bar.open_time_ms))
      || (i > 0 && bar.open_time_ms <= bars[i - 1]!.open_time_ms)) throw new TypeError("tape projection crossed its revealed boundary");
  }
  if (bars.length && row.next_before_ms !== bars[0]!.open_time_ms) throw new TypeError("tape history cursor does not match its page");
  const identity = parseIdentity(row.identity, "tape.identity");
  if (identity.source_kind !== "AGG_TRADE" || identity.display_interval !== row.display_interval) throw new TypeError("tape identity changed");
  const history_policy = parseHistoryPolicy(row.history_policy, "tape.history_policy");
  return { ...(row as unknown as ReplayTapeProjection), bars, identity, history_policy };
}

export async function loadReplayTapeProjection(
  load: (signal?: AbortSignal) => Promise<ReplayTapeProjection>,
  signal: AbortSignal,
  progress: (prepared: number, target: number, phase: "context" | "trades") => void = () => {},
  options: { pendingRetryDelaysMs?: readonly number[]; pending?: () => void } = {},
): Promise<ReplayTapeProjection> {
  const previous = { context: -1, trades: -1 };
  const pendingDelays = options.pendingRetryDelaysMs ?? [1_000, 2_000, 4_000, 5_000, 5_000, 5_000];
  let pendingAttempts = 0;
  let identity: string | null = null;
  while (true) {
    signal.throwIfAborted();
    let result: ReplayTapeProjection;
    try {
      result = await load(signal);
    } catch (error) {
      signal.throwIfAborted();
      const delay = replayHistoryRetryDelay(error, pendingAttempts, pendingDelays);
      if (delay === undefined) throw error;
      pendingAttempts++;
      options.pending?.();
      await waitForTapePreparation(delay, signal);
      continue;
    }
    signal.throwIfAborted();
    pendingAttempts = 0;
    const current = JSON.stringify([result.session_id, result.track_id, result.data_epoch, result.display_interval,
      result.source_sequence, result.revealed_boundary_ms, result.before_ms, result.target_sequence, result.history_boundary_ms,
      result.history_epoch, result.history_scope, result.context_target_before_ms, result.run_id, result.identity, result.history_policy]);
    if (identity !== null && identity !== current) throw new TypeError("tape preparation source changed");
    identity = current;
    if (result.status === "ready") return result;
    const phase = result.context_prepared_before_ms < result.context_target_before_ms ? "context" : "trades";
    if (phase === "context" && previous.trades >= 0) throw new TypeError("tape preparation returned to an earlier phase");
    const prepared = phase === "context" ? result.context_prepared_before_ms : result.prepared_sequence;
    const target = phase === "context" ? result.context_target_before_ms : result.target_sequence;
    if (prepared <= previous[phase]) throw new TypeError("tape preparation did not progress");
    previous[phase] = prepared;
    progress(prepared, target, phase);
    await waitForTapePreparation(50, signal);
  }
}

function waitForTapePreparation(delay: number, signal: AbortSignal): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const abort = () => { clearTimeout(timer); signal.removeEventListener("abort", abort); reject(new DOMException("tape preparation cancelled", "AbortError")); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, delay);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
  });
}
