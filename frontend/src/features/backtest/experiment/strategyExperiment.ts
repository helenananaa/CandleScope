/**
 * Experiments (ADR-BACKTEST-015 §3.6, steps P5b and P5c3): one strategy run by a rule, held by the
 * backend. INPUTS runs it over several inputs: each member is a strategy data preparation that starts
 * its run when its exchange history is ready, or a run over a frozen snapshot. ROBUSTNESS is a Study
 * V2: its members are the runs the study planned (candidates on training windows, the selected one
 * out of sample, the holdout). A member's state is read from its preparation or run.
 */
export const STRATEGY_EXPERIMENT_SCHEMA = "candlescope.strategy-experiment/1";
export const STRATEGY_EXPERIMENT_STREAM_SCHEMA = "candlescope.strategy-experiment-stream/1";

/** AWAITING_HOLDOUT: a robustness study finished its folds and waits for the user to open its holdout. */
export type ExperimentState = "RUNNING" | "AWAITING_HOLDOUT" | "COMPLETED" | "FAILED" | "CANCELLED";
export type ExperimentKind = "INPUTS" | "ROBUSTNESS";
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

export interface StudyWindow { startMs: number; endMs: number }

/** A robustness experiment's study: its rule, each fold's selection, the holdout and the out-of-sample verdict. */
export interface ExperimentStudy {
  studyId: string;
  state: string;
  hypothesis: string;
  objective: string | null;
  sampler: string | null;
  candidates: number | null;
  parameterSpace: Record<string, unknown>;
  window: StudyWindow | null;
  /** The imported dataset the study runs over. */
  dataset: { datasetId: string; dataEpoch: string; interval: string } | null;
  folds: Array<{ ordinal: number; state: string; train: StudyWindow; test: StudyWindow; selected: Record<string, unknown> | null }>;
  holdout: { state: string; window: StudyWindow; parameters: Record<string, unknown> | null } | null;
  /** The out-of-sample report: summary, per-fold rows and the robustness checks, as served. */
  oos: { summary: Record<string, unknown> | null; folds: Array<Record<string, unknown>>; robustness: Record<string, unknown> | null } | null;
  error: ExperimentError | null;
}

export interface StrategyExperiment {
  experimentId: string;
  name: string;
  kind: ExperimentKind;
  strategy: Record<string, unknown>;
  createdAtMs: number;
  cancelledAtMs: number | null;
  state: ExperimentState;
  terminal: boolean;
  counts: { total: number; completed: number; failed: number; cancelled: number; active: number };
  members: ExperimentMember[];
  /** ROBUSTNESS only. */
  study: ExperimentStudy | null;
}

export class StrategyExperimentContractError extends Error {
  constructor(message: string) {
    super(`strategy-experiment: ${message}`);
    this.name = "StrategyExperimentContractError";
  }
}

const EXPERIMENT_STATES: readonly ExperimentState[] = ["RUNNING", "AWAITING_HOLDOUT", "COMPLETED", "FAILED", "CANCELLED"];
const KINDS: readonly ExperimentKind[] = ["INPUTS", "ROBUSTNESS"];
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

function optionalRecord(value: unknown, at: string): Record<string, unknown> | null {
  return value === null || value === undefined ? null : record(value, at);
}

function window(value: unknown, at: string): StudyWindow {
  const body = record(value, at);
  return { startMs: count(body.start_ms, `${at}.start_ms`), endMs: count(body.end_ms, `${at}.end_ms`) };
}

function study(value: unknown, at: string): ExperimentStudy {
  const body = record(value, at);
  const holdout = optionalRecord(body.holdout, `${at}.holdout`);
  const oos = optionalRecord(body.oos, `${at}.oos`);
  const dataset = optionalRecord(body.dataset, `${at}.dataset`);
  return {
    studyId: text(body.study_id, `${at}.study_id`), state: text(body.state, `${at}.state`),
    hypothesis: typeof body.hypothesis === "string" ? body.hypothesis : "",
    objective: typeof body.objective === "string" ? body.objective : null,
    sampler: typeof body.sampler === "string" ? body.sampler : null,
    candidates: body.candidates === null || body.candidates === undefined ? null : count(body.candidates, `${at}.candidates`),
    parameterSpace: optionalRecord(body.parameter_space, `${at}.parameter_space`) ?? {},
    window: body.window === null || body.window === undefined ? null : window(body.window, `${at}.window`),
    dataset: dataset && typeof dataset.dataset_id === "string" && typeof dataset.data_epoch === "string"
      ? { datasetId: dataset.dataset_id, dataEpoch: dataset.data_epoch, interval: String(dataset.interval ?? "") } : null,
    folds: (Array.isArray(body.folds) ? body.folds : []).map((item, index) => {
      const fold = record(item, `${at}.folds[${index}]`);
      return { ordinal: count(fold.ordinal, `${at}.folds[${index}].ordinal`), state: text(fold.state, `${at}.folds[${index}].state`),
        train: window(fold.train, `${at}.folds[${index}].train`), test: window(fold.test, `${at}.folds[${index}].test`),
        selected: optionalRecord(fold.selected, `${at}.folds[${index}].selected`) };
    }),
    holdout: holdout && { state: text(holdout.state, `${at}.holdout.state`), window: window(holdout, `${at}.holdout`),
      parameters: optionalRecord(holdout.parameters, `${at}.holdout.parameters`) },
    oos: oos && { summary: optionalRecord(oos.summary, `${at}.oos.summary`),
      folds: (Array.isArray(oos.folds) ? oos.folds : []).map((item, index) => record(item, `${at}.oos.folds[${index}]`)),
      robustness: optionalRecord(oos.robustness, `${at}.oos.robustness`) },
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
    experimentId, name: text(body.name, "name"), kind: oneOf(body.kind, KINDS, "kind"),
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
    study: body.study === null || body.study === undefined ? null : study(body.study, "study"),
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
