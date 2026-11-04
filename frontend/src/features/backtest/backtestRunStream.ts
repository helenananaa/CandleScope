import type { BacktestRunRecord } from "./backtestTypes.js";

export interface StrategyRunProgress {
  sequence: number;
  generation: number;
  state_hash: string;
  created_at_ms: number;
}

export interface StrategyRunUpdate {
  type: "status" | "progress" | "completed";
  run: BacktestRunRecord;
  progress: StrategyRunProgress | null;
  result?: Record<string, unknown>;
}

export class StrategyRunStreamError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
    this.name = "StrategyRunStreamError";
  }
}

const identityFields = ["run_id", "generation", "strategy_revision_id", "dataset_id", "data_epoch",
  "snapshot_hash", "config_hash", "engine_version", "fidelity_mode", "source_event_kind"] as const;
const terminalStates = new Set(["COMPLETED", "FAILED", "CANCELLED"]);
const runStates = new Set(["DRAFT", "VALIDATING", "QUEUED", "PREPARING", "RUNNING", "PAUSING", "PAUSED", "COMPLETING", "CANCELLING", ...terminalStates]);

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) invalid();
  return value as Record<string, unknown>;
}
function invalid(message = "Invalid strategy result stream"): never {
  throw new StrategyRunStreamError("STRATEGY_STREAM_INVALID", message);
}
function serverError(value: unknown): never {
  const error = object(value);
  if (typeof error.code !== "string" || !error.code || typeof error.message !== "string" || !error.message) invalid();
  throw new StrategyRunStreamError(error.code, error.message);
}

/** Consume one finite committed run stream. EOF before a terminal frame is an
 * error; releasing this reader does not cancel the durable backend run. */
export async function readStrategyRunStream(input: {
  body: ReadableStream<Uint8Array>;
  runId: string;
  signal?: AbortSignal;
  onUpdate?: (update: StrategyRunUpdate) => void;
  maxFrameCharacters?: number;
}): Promise<BacktestRunRecord> {
  input.signal?.throwIfAborted();
  const reader = input.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  const limit = input.maxFrameCharacters ?? 8 * 1024 * 1024;
  let buffer = "";
  let identity: string | null = null;
  const abort = () => { void reader.cancel(input.signal?.reason).catch(() => {}); };
  input.signal?.addEventListener("abort", abort, { once: true });
  const parse = (line: string): BacktestRunRecord | null => {
    if (line.length > limit) invalid("Strategy result frame exceeds the consumer limit");
    let raw: unknown;
    try { raw = JSON.parse(line); } catch { invalid(); }
    const frame = object(raw);
    if (frame.schema !== "candlescope.strategy-run-events/1") invalid();
    if (frame.type === "heartbeat") {
      if (frame.terminal !== false) invalid();
      return null;
    }
    if (frame.type === "error") {
      if (frame.terminal !== true || (frame.run_id !== undefined && frame.run_id !== input.runId)) invalid();
      if (frame.run !== undefined && object(frame.run).run_id !== input.runId) invalid();
      serverError(frame.error);
    }
    const run = object(frame.run);
    if (run.run_id !== input.runId || typeof run.state !== "string" || !runStates.has(run.state)
      || !Number.isSafeInteger(run.generation) || Number(run.generation) < 1
      || identityFields.filter((key) => key !== "generation").some((key) => typeof run[key] !== "string" || !run[key])) invalid();
    const key = JSON.stringify(identityFields.map((field) => run[field]));
    if (identity !== null && identity !== key) invalid("Strategy stream changed its fixed run identity");
    identity = key;
    if (frame.type === "failed") {
      if (frame.terminal !== true || run.state !== "FAILED") invalid();
      serverError(frame.error);
    }
    if (frame.type === "cancelled") {
      if (frame.terminal !== true || run.state !== "CANCELLED") invalid();
      throw new StrategyRunStreamError("RUN_CANCELLED", "The strategy run was cancelled");
    }
    let progress: StrategyRunProgress | null = null;
    if (frame.progress !== null && frame.progress !== undefined) {
      const value = object(frame.progress);
      if (!Number.isSafeInteger(value.sequence) || Number(value.sequence) < 0
        || !Number.isSafeInteger(value.generation) || Number(value.generation) < 1
        || Number(value.generation) > Number(run.generation)
        || typeof value.state_hash !== "string" || !value.state_hash
        || !Number.isSafeInteger(value.created_at_ms)) invalid();
      progress = value as unknown as StrategyRunProgress;
    }
    const record = run as unknown as BacktestRunRecord;
    if (frame.type === "completed") {
      if (frame.terminal !== true || run.state !== "COMPLETED") invalid();
      const result = object(frame.result), summary = object(result.summary);
      if (typeof result.report_hash !== "string" || !result.report_hash
        || summary.schemaVersion !== "backtest.report-summary/1"
        || summary.runId !== input.runId || summary.reportHash !== result.report_hash) invalid();
      input.onUpdate?.({ type: "completed", run: record, progress, result });
      input.signal?.throwIfAborted();
      return record;
    }
    if ((frame.type !== "status" && frame.type !== "progress") || frame.terminal !== false || terminalStates.has(run.state)) invalid();
    input.onUpdate?.({ type: frame.type, run: record, progress });
    return null;
  };
  try {
    while (true) {
      const { value, done } = await reader.read();
      input.signal?.throwIfAborted();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      let newline: number;
      while ((newline = buffer.indexOf("\n")) >= 0) {
        if (newline > limit) invalid("Strategy result frame exceeds the consumer limit");
        const line = buffer.slice(0, newline).trim();
        buffer = buffer.slice(newline + 1);
        if (!line) continue;
        const terminal = parse(line);
        if (terminal) return terminal;
      }
      if (buffer.length > limit) invalid("Strategy result frame exceeds the consumer limit");
      if (done) {
        if (buffer.trim()) {
          const terminal = parse(buffer.trim());
          if (terminal) return terminal;
        }
        throw new StrategyRunStreamError("STRATEGY_STREAM_INCOMPLETE", "The strategy result stream ended before completion");
      }
    }
  } finally {
    input.signal?.removeEventListener("abort", abort);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
