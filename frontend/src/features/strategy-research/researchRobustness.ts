/**
 * A robustness check in the research workspace (ADR-BACKTEST-015 P5c3): the strategy's parameter
 * candidates trained on walk-forward folds, one selected per fold and tested out of sample, then an
 * optional holdout. The backend runs it as a Study V2 experiment; this module turns the workspace's
 * form into the study's rule, and estimates how many runs it plans.
 */

export const ROBUSTNESS_OBJECTIVES = ["NET_RETURN", "SHARPE", "CALMAR", "EXPECTANCY"] as const;
export type RobustnessObjective = typeof ROBUSTNESS_OBJECTIVES[number];

export interface RobustnessForm {
  hypothesis: string;
  /** JSON object: each parameter and the values to try. */
  space: string;
  trainBars: number;
  testBars: number;
  /** Bars between fold starts; at least the test length, so test windows never overlap. */
  stepBars: number;
  /** Bars kept sealed at the end until the user opens them. */
  holdoutBars: number;
  sampler: "grid" | "random";
  candidates: number;
  objective: RobustnessObjective;
  /** JSON object: the study's other settings (constraints, costs, sizing, purge and embargo, seed). */
  advanced: string;
}

/** The study's window: whole bars of the research range, start inclusive and end exclusive. */
export interface StudyRange { startMs: number; endMs: number; intervalMs: number; bars: number }

/** Why the form cannot start a study, as a message key. */
export type RobustnessErrorKey = "researchRobustness.needHypothesis" | "researchRobustness.invalidSpace"
  | "researchRobustness.invalidWindows" | "researchRobustness.tooShort" | "researchRobustness.invalidAdvanced";

export class RobustnessFormError extends Error {
  constructor(readonly key: RobustnessErrorKey) {
    super(key);
    this.name = "RobustnessFormError";
  }
}

/** The study's own settings the advanced JSON starts from (as the research tool's Study V2 draft did). */
export const ROBUSTNESS_ADVANCED_DEFAULTS: Readonly<Record<string, unknown>> = Object.freeze({
  purge_ms: 0, embargo_ms: 0, seed: 24, warmup_bars: 0,
  constraints: { min_closed_trades: 1, max_drawdown: "0.5", min_data_coverage: "1", max_ambiguity_ratio: "0",
    max_rejected_ratio: "0", cost_plus_25_must_be_positive: false, warn_min_long_trades: 1, warn_min_short_trades: 1 },
  initial_balance: "10000", slippage_bps: "1", taker_fee_bps: "0", maker_fee_bps: "0", funding_mode: "OFF",
  participation_rate: "0.1", risk_free_rate_annual: "0", sizing_policy: "FIXED_QTY_V1", fixed_qty: "1",
});

/** Fields the form, the strategy or the data decide; the advanced JSON may not set them. */
const OWNED = new Set(["name", "hypothesis", "parameter_space", "parameters", "sampler", "candidate_budget", "max_trials",
  "random_count", "objective", "train_ms", "test_ms", "step_ms", "holdout_ms", "start_ms", "end_ms", "interval",
  "strategy_revision_id", "dataset_id", "data_epoch", "dataset_snapshot_hash", "dataset_basket", "total_run_budget",
  "study_protocol_revision", "selection_protocol_revision", "python_runtime_mode", "python_trusted_confirmed"]);

/** A fixed bar length ("15m", "4h", "1d"); null when the interval has none ("1w", "1M" months). */
export function fixedIntervalMs(interval: string): number | null {
  const match = /^(\d+)([mhd])$/.exec(interval.trim());
  if (!match) return null;
  const amount = Number(match[1]);
  const unit = match[2] === "m" ? 60_000 : match[2] === "h" ? 3_600_000 : 86_400_000;
  return Number.isSafeInteger(amount) && amount > 0 ? amount * unit : null;
}

/**
 * The whole bars of an imported dataset's research range. ``range.endMs`` is exclusive; the last bar
 * is the one opening before it, and it is kept whole (the study ends at its close).
 */
export function studyRange(dataset: { interval: string; first_open_ms: number; last_open_ms: number },
  range: { startMs: number; endMs: number }): StudyRange | null {
  const step = fixedIntervalMs(dataset.interval);
  if (step === null) return null;
  const startMs = Math.ceil(Math.max(range.startMs, dataset.first_open_ms) / step) * step;
  const lastOpen = Math.floor(Math.min(range.endMs - 1, dataset.last_open_ms) / step) * step;
  const endMs = lastOpen + step;
  const bars = (endMs - startMs) / step;
  return bars >= 2 ? { startMs, endMs, intervalMs: step, bars } : null;
}

/** The form a new check starts from: 60% of the range to train, 20% to test, today's parameter values. */
export function defaultRobustnessForm(range: StudyRange, parameters: Record<string, unknown>): RobustnessForm {
  const testBars = Math.max(1, Math.floor(range.bars * 0.2));
  const trainBars = Math.max(1, Math.min(range.bars - testBars, Math.floor(range.bars * 0.6)));
  const space = Object.fromEntries(Object.entries(parameters)
    .filter(([name, value]) => !name.startsWith("__") && ["number", "string", "boolean"].includes(typeof value))
    .map(([name, value]) => [name, [value]]));
  return { hypothesis: "", space: JSON.stringify(space, null, 2), trainBars, testBars, stepBars: testBars, holdoutBars: 0,
    sampler: "grid", candidates: 4, objective: "NET_RETURN", advanced: JSON.stringify(ROBUSTNESS_ADVANCED_DEFAULTS, null, 2) };
}

function jsonObject(text: string, key: RobustnessErrorKey): Record<string, unknown> {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new RobustnessFormError(key);
  }
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new RobustnessFormError(key);
  return value as Record<string, unknown>;
}

function wholeBars(value: number, minimum: number): boolean {
  return Number.isSafeInteger(value) && value >= minimum;
}

/** The parameter space: each parameter lists at least one plain value to try. */
export function parseParameterSpace(text: string): Record<string, unknown[]> {
  const space = jsonObject(text, "researchRobustness.invalidSpace");
  const entries = Object.entries(space);
  if (!entries.length || entries.some(([name, values]) => name.startsWith("__") || !Array.isArray(values) || !values.length
    || values.some((item) => item === null || !["number", "string", "boolean"].includes(typeof item)))) {
    throw new RobustnessFormError("researchRobustness.invalidSpace");
  }
  return space as Record<string, unknown[]>;
}

/** How many folds and runs the study plans (purge and embargo as the advanced JSON sets them). */
export function robustnessPlan(form: RobustnessForm, range: StudyRange): { folds: number; candidates: number; runs: number } {
  let candidates = 0;
  try {
    const sizes = Object.values(parseParameterSpace(form.space)).map((values) => values.length);
    candidates = Math.min(Math.max(0, Math.floor(form.candidates)), sizes.reduce((total, size) => total * size, 1));
  } catch { /* the space is being edited */ }
  let advanced: Record<string, unknown> = {};
  try { advanced = jsonObject(form.advanced, "researchRobustness.invalidAdvanced"); } catch { /* being edited */ }
  const step = range.intervalMs;
  const embargo = Number(advanced.embargo_ms) || 0;
  const researchEnd = range.endMs - form.holdoutBars * step;
  let folds = 0;
  if (form.trainBars > 0 && form.testBars > 0 && form.stepBars >= form.testBars) {
    for (let cursor = range.startMs; cursor + form.trainBars * step + embargo + form.testBars * step <= researchEnd; cursor += form.stepBars * step) {
      folds += 1;
      if (folds > 10_000) break;
    }
  }
  return { folds, candidates, runs: folds * (candidates + 1) + (form.holdoutBars > 0 && folds > 0 ? 1 : 0) };
}

/** The study's rule from the form, over the range. Throws ``RobustnessFormError`` with a message key. */
export function robustnessStudyFields(form: RobustnessForm, range: StudyRange): Record<string, unknown> {
  const hypothesis = form.hypothesis.trim();
  if (!hypothesis) throw new RobustnessFormError("researchRobustness.needHypothesis");
  const space = parseParameterSpace(form.space);
  const advanced = jsonObject(form.advanced, "researchRobustness.invalidAdvanced");
  if (Object.keys(advanced).some((key) => OWNED.has(key))) throw new RobustnessFormError("researchRobustness.invalidAdvanced");
  if (!wholeBars(form.trainBars, 1) || !wholeBars(form.testBars, 1) || !wholeBars(form.stepBars, form.testBars)
    || !wholeBars(form.holdoutBars, 0) || !wholeBars(form.candidates, 1)) {
    throw new RobustnessFormError("researchRobustness.invalidWindows");
  }
  if (!ROBUSTNESS_OBJECTIVES.includes(form.objective) || (form.sampler !== "grid" && form.sampler !== "random")) {
    throw new RobustnessFormError("researchRobustness.invalidWindows");
  }
  if (robustnessPlan(form, range).folds < 1) throw new RobustnessFormError("researchRobustness.tooShort");
  const step = range.intervalMs;
  return {
    ...advanced,
    hypothesis, parameter_space: space, sampler: form.sampler, candidate_budget: form.candidates, objective: form.objective,
    start_ms: range.startMs, end_ms: range.endMs,
    train_ms: form.trainBars * step, test_ms: form.testBars * step, step_ms: form.stepBars * step, holdout_ms: form.holdoutBars * step,
  };
}
