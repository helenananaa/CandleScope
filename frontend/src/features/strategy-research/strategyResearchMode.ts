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
 * The mode the page opens in: `?mode=` when given, otherwise the research tool a
 * compatibility URL or deep link implies. Null means a launch context picks its own tool.
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

export function isResearchToolMode(mode: StrategyResearchMode | null): boolean {
  return mode === null || researchTaskForMode(mode) !== null;
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
