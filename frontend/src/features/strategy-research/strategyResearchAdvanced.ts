import { defaultBacktestApi } from "../backtest/backtestApi.js";
import { buildBacktestResearchLaunchContext } from "../backtest/research/backtestResearchLaunch.js";
import type { ChartStrategyResultBundle } from "../backtest/chart-tester/chartStrategyResultCache.js";
import { chartStrategyQuickPresetIdForMarket } from "../backtest/chart-tester/chartStrategyRunRequest.js";
import type { ChartSession } from "../chart-session/chartSessionTypes.js";
import type { ResearchSourceRefV1 } from "../research-data/researchDataTypes.js";
import type { StrategyRunSettings } from "../../shared/strategyRunSettings.js";

export function strategyResearchAdvancedCellId(source: ResearchSourceRefV1 | null): "imported" | "current" {
  return source?.kind === "IMPORTED_DATASET" ? "imported" : "current";
}

/**
 * Carries the quick test's source, strategy draft and latest result into the research tools:
 * creates a launch context and returns the search that opens it (`?context=…`).
 */
export async function createStrategyResearchContextSearch(input: {
  source: ResearchSourceRefV1 | null;
  session: ChartSession;
  draftId: string;
  result: ChartStrategyResultBundle | null;
  configuration?: StrategyRunSettings | undefined;
}): Promise<string> {
  const payload = buildBacktestResearchLaunchContext({
    workspaceId: "strategy-research",
    cellId: strategyResearchAdvancedCellId(input.source),
    session: input.session,
    attachment: {
      schemaVersion: 1,
      strategyDraftId: input.draftId,
      strategyRevisionId: null,
      displayName: "Strategy",
      language: "python",
      parameters: {},
      rangeMode: "ALL_AVAILABLE",
      customRange: null,
      fidelityPreference: "FAST",
      quickPresetId: chartStrategyQuickPresetIdForMarket(input.session.marketType),
      autoRun: false,
      ...input.configuration,
    },
    result: input.result,
    resolution: null,
    activeRunId: input.result?.run.run_id ?? null,
    baselineRunId: null,
  });
  const context = await defaultBacktestApi.createResearchLaunchContext(payload);
  if (!/^brc_[A-Za-z0-9_-]{8,128}$/.test(context.context_id)) {
    throw new Error("Invalid BacktestResearchLaunchContext ID");
  }
  return `?context=${encodeURIComponent(context.context_id)}`;
}
