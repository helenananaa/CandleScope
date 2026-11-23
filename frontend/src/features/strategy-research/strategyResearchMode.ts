import {
  researchTaskForMode,
  strategyResearchModeFromSearch,
  type StrategyResearchMode,
} from "../backtest/research/backtestResearchModes.js";
import { strategyResearchPageFromPathname, type StrategyResearchLaunchIntent } from "./strategyResearchLaunch.js";

export {
  researchModeForTask,
  researchTaskForMode,
  strategyResearchModeHref,
  STRATEGY_RESEARCH_MODES,
  type StrategyResearchMode,
  type StrategyResearchToolMode,
} from "../backtest/research/backtestResearchModes.js";

/**
 * The mode the page opens in: `?mode=` when given, otherwise what a compatibility URL or deep link
 * implies. The workspace opens that mode's field; a deep link opens that research tool (until P5d).
 * Null means a launch context picks its own tool.
 */
export function initialStrategyResearchMode(
  intent: StrategyResearchLaunchIntent,
  search: string,
): StrategyResearchMode | null {
  const explicit = strategyResearchModeFromSearch(search);
  if (explicit !== null) return explicit;
  if (intent.kind === "advanced") return "precise";
  if (intent.kind === "deep-link") {
    if (intent.entry.kind === "study") return "robust";
    if (intent.entry.kind === "run") return "precise";
    return null;
  }
  return "quick";
}

/** What `?mode=` opens in the workspace (ADR-BACKTEST-015 P5c4): the field each research tool became. */
export interface ResearchWorkspaceFocus {
  /** The strategy panel's pane: run settings (fill accuracy and costs) for precise runs. */
  pane?: "conditions";
  robustness?: boolean;
  batch?: boolean;
  /** Python packages and the builtin strategies. */
  saved?: boolean;
  /** The result's details: data quality, fill model, signal log, review in training replay. */
  resultTab?: "details";
}

export function researchWorkspaceFocus(mode: StrategyResearchMode | null): ResearchWorkspaceFocus {
  switch (mode) {
    case "precise": return { pane: "conditions", resultTab: "details" };
    case "robust": return { robustness: true };
    case "python": return { saved: true };
    case "multi": return { batch: true };
    case "replay": return { resultTab: "details" };
    default: return {};
  }
}

/** The research tool's own task for a mode (null: a launch context picks its task). */
export function researchToolTask(mode: StrategyResearchMode | null) {
  return mode === null ? null : researchTaskForMode(mode);
}

/**
 * backtest.html and local.html are compatibility URLs: the page rewrites its address
 * to strategy.html in the matching mode. Returns null when already canonical.
 */
export function canonicalStrategyResearchHref(
  location: { pathname: string; search: string },
  intent: StrategyResearchLaunchIntent,
): string | null {
  const page = strategyResearchPageFromPathname(location.pathname);
  if (page === "strategy") return null;
  const original = new URLSearchParams(location.search.startsWith("?") ? location.search : `?${location.search}`);
  const params = new URLSearchParams();
  if (page === "backtest") {
    const mode = initialStrategyResearchMode(intent, location.search);
    if (mode !== null) params.set("mode", mode);
  } else if (!original.has("source") && !original.has("action") && intent.kind !== "deep-link") {
    params.set("source", "imported");
  }
  for (const [key, value] of original) {
    if (key !== "mode") params.set(key, value);
  }
  const search = params.toString();
  return `/strategy.html${search ? `?${search}` : ""}`;
}
