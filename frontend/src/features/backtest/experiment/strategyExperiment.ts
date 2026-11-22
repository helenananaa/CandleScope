/**
 * Experiments (ADR-BACKTEST-015 §3.6, step P5b): one strategy run over several inputs, held by the
 * backend. Each member is a strategy data preparation that starts its run when its exchange
 * history is ready, or a run over a frozen snapshot; its state is read from that preparation or run.
 */
export const STRATEGY_EXPERIMENT_SCHEMA = "candlescope.strategy-experiment/1";
export const STRATEGY_EXPERIMENT_STREAM_SCHEMA = "candlescope.strategy-experiment-stream/1";

export type ExperimentState = "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
export type ExperimentMemberState = "PENDING" | "PREPARING" | "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";

export interface ExperimentError { code: string; message: string }

export interface ExperimentPreparation {
  id: string;
  state: string;
  stage: string | null;
  completed: number;
  total: number;
  /** Why the preparation waits (for example the source's rate limit), as served. */
  waiting: Record<string, unknown> | null;
  error: ExperimentError | null;
}

export interface ExperimentMember {
  ordinal: number;
  /** What the member runs over, as the page described it (a dataset, an exchange range). */
  input: Record<string, unknown>;
  kind: "PREPARATION" | "RUN";
  attempt: number;
  state: ExperimentMemberState;
  preparation: ExperimentPreparation | null;
  runId: string | null;
  error: ExperimentError | null;
}

export interface StrategyExperiment {
  experimentId: string;
  name: string;
  kind: "INPUTS";
  strategy: Record<string, unknown>;
  createdAtMs: number;
  cancelledAtMs: number | null;
  state: ExperimentState;
  terminal: boolean;
  counts: { total: number; completed: number; failed: number; cancelled: number; active: number };
  members: ExperimentMember[];
}

export class StrategyExperimentContractError extends Error {
  constructor(message: string) {
    super(`strategy-experiment: ${message}`);
    this.name = "StrategyExperimentContractError";
  }
}

const EXPERIMENT_STATES: readonly ExperimentState[] = ["RUNNING", "COMPLETED", "FAILED", "CANCELLED"];
const MEMBER_STATES: readonly ExperimentMemberState[] = ["PENDING", "PREPARING", "QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"];

function record(value: unknown, at: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new StrategyExperimentContractError(`${at} must be an object`);
  return value as Record<string, unknown>;
}

function text(value: unknown, at: string): string {
  if (typeof value !== "string" || !value) throw new StrategyExperimentContractError(`${at} must be text`);
  return value;
}

function count(value: unknown, at: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) throw new StrategyExperimentContractError(`${at} must be a count`);
  return value;
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[], at: string): T {
  if (typeof value !== "string" || !(allowed as readonly string[]).includes(value)) {
    throw new StrategyExperimentContractError(`${at} must be one of ${allowed.join(", ")}`);
  }
  return value as T;
}

function error(value: unknown, at: string): ExperimentError | null {
  if (value === null || value === undefined) return null;
  const body = record(value, at);
  return { code: text(body.code, `${at}.code`), message: String(body.message ?? body.code) };
}

function preparation(value: unknown, at: string): ExperimentPreparation | null {
  if (value === null || value === undefined) return null;
  const body = record(value, at);
  return {
    id: text(body.id, `${at}.id`), state: text(body.state, `${at}.state`),
    stage: typeof body.stage === "string" ? body.stage : null,
    completed: count(body.completed, `${at}.completed`), total: count(body.total, `${at}.total`),
    waiting: body.waiting === null || body.waiting === undefined ? null : record(body.waiting, `${at}.waiting`),
    error: error(body.error, `${at}.error`),
  };
}

/** Validate a served experiment. */
export function parseStrategyExperiment(value: unknown): StrategyExperiment {
  const body = record(value, "experiment");
  if (body.schema !== STRATEGY_EXPERIMENT_SCHEMA) throw new StrategyExperimentContractError(`schema must be ${STRATEGY_EXPERIMENT_SCHEMA}`);
  const experimentId = text(body.experiment_id, "experiment_id");
  if (!experimentId.startsWith("ex_")) throw new StrategyExperimentContractError("experiment_id must be an experiment id");
  if (!Array.isArray(body.members)) throw new StrategyExperimentContractError("members must be a list");
  const counts = record(body.counts, "counts");
  const state = oneOf(body.state, EXPERIMENT_STATES, "state");
  return {
    experimentId, name: text(body.name, "name"), kind: oneOf(body.kind, ["INPUTS"] as const, "kind"),
    strategy: record(body.strategy, "strategy"), createdAtMs: count(body.created_at_ms, "created_at_ms"),
    cancelledAtMs: body.cancelled_at_ms === null || body.cancelled_at_ms === undefined ? null : count(body.cancelled_at_ms, "cancelled_at_ms"),
    state, terminal: state !== "RUNNING",
    counts: { total: count(counts.total, "counts.total"), completed: count(counts.completed, "counts.completed"),
      failed: count(counts.failed, "counts.failed"), cancelled: count(counts.cancelled, "counts.cancelled"),
      active: count(counts.active, "counts.active") },
    members: body.members.map((item, index) => {
      const at = `members[${index}]`;
      const member = record(item, at);
      const runId = member.run_id === null || member.run_id === undefined ? null : text(member.run_id, `${at}.run_id`);
      return {
        ordinal: count(member.ordinal, `${at}.ordinal`), input: record(member.input, `${at}.input`),
        kind: oneOf(member.kind, ["PREPARATION", "RUN"] as const, `${at}.kind`), attempt: count(member.attempt, `${at}.attempt`),
        state: oneOf(member.state, MEMBER_STATES, `${at}.state`), preparation: preparation(member.preparation, `${at}.preparation`),
        runId, error: error(member.error, `${at}.error`),
      };
    }),
  };
}

/** One `candlescope.strategy-experiment-stream/1` frame; heartbeats parse to null. */
export function parseStrategyExperimentFrame(value: unknown): { experiment: StrategyExperiment } | { error: ExperimentError } | null {
  const frame = record(value, "frame");
  if (frame.schema !== STRATEGY_EXPERIMENT_STREAM_SCHEMA) throw new StrategyExperimentContractError(`frame schema must be ${STRATEGY_EXPERIMENT_STREAM_SCHEMA}`);
  if (frame.type === "heartbeat") return null;
  if (frame.type === "error") return { error: error(frame.error, "frame.error") ?? { code: "STRATEGY_STREAM_FAILED", message: "stream failed" } };
  if (frame.type !== "status") throw new StrategyExperimentContractError("frame type must be status, heartbeat or error");
  return { experiment: parseStrategyExperiment(frame.experiment) };
}
