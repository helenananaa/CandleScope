import type { BacktestRunRecord } from "../backtestTypes.js";

/**
 * Helpers the research workspace kept from the research tools (ADR-BACKTEST-015 P5d): JSON objects the
 * user edits, a run's stored configuration, and the link to a review in training replay.
 */
const SAFE_REPLAY_RUN_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

function objectValue(value: unknown, field: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${field} must be a JSON object`);
  }
  return value as Record<string, unknown>;
}

export function parseResearchObjectJson(text: string, field: string): Record<string, unknown> {
  return objectValue(JSON.parse(text) as unknown, field);
}

export function parseResearchRunConfig(run: BacktestRunRecord | null): Record<string, unknown> {
  if (!run?.config_json) return {};
  try {
    return objectValue(JSON.parse(run.config_json) as unknown, "Run config");
  } catch {
    return {};
  }
}

export function researchReplayHref(bridge: Record<string, unknown> | null): string | null {
  const training = bridge?.trainingRun;
  const direct = training && typeof training === "object" && !Array.isArray(training)
    ? (training as Record<string, unknown>).run_id
    : bridge?.trainingRunId;
  const runId = typeof direct === "string" ? direct : "";
  if (!SAFE_REPLAY_RUN_ID.test(runId)) return null;
  return `/replay.html?run=${encodeURIComponent(runId)}`;
}
