import type { BacktestResearchTask } from "./backtestResearchTypes.js";

/**
 * Modes of the one strategy research page (strategy.html?mode=…): 快速测试 plus
 * one per research tool. The research tools keep their task names internally.
 */
export const STRATEGY_RESEARCH_MODES = ["quick", "precise", "robust", "python", "multi", "replay"] as const;
export type StrategyResearchMode = typeof STRATEGY_RESEARCH_MODES[number];
export type StrategyResearchToolMode = Exclude<StrategyResearchMode, "quick">;

const MODE_TASK: Readonly<Record<StrategyResearchToolMode, BacktestResearchTask>> = {
  precise: "PRECISE_EXECUTION",
  robust: "PARAMETER_ROBUSTNESS",
  python: "PYTHON_MODEL",
  multi: "MULTI_MARKET",
  replay: "REPLAY_REVIEW",
};

export function isStrategyResearchMode(value: unknown): value is StrategyResearchMode {
  return typeof value === "string" && (STRATEGY_RESEARCH_MODES as readonly string[]).includes(value);
}

export function researchTaskForMode(mode: StrategyResearchMode): BacktestResearchTask | null {
  return mode === "quick" ? null : MODE_TASK[mode];
}

export function researchModeForTask(task: BacktestResearchTask): StrategyResearchToolMode {
  const entry = (Object.entries(MODE_TASK) as Array<[StrategyResearchToolMode, BacktestResearchTask]>)
    .find(([, value]) => value === task);
  return entry?.[0] ?? "precise";
}

/** The mode named by `?mode=`, or null when absent or unknown. */
export function strategyResearchModeFromSearch(search: string): StrategyResearchMode | null {
  const value = new URLSearchParams(search.startsWith("?") ? search : `?${search}`).get("mode")?.trim() ?? "";
  return isStrategyResearchMode(value) ? value : null;
}

/** Canonical link to the strategy research page in a mode, with deep-link parameters (context, run, study, compare, source). */
export function strategyResearchModeHref(
  mode: StrategyResearchMode,
  params: Readonly<Record<string, string | null | undefined>> = {},
): string {
  const search = new URLSearchParams({ mode });
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") search.set(key, value);
  }
  return `/strategy.html?${search.toString()}`;
}
