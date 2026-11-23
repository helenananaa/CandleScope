/**
 * Research links in the workspace (ADR-BACKTEST-015 P5d): a `?run=` link shows the run on the data it
 * used, and an older `?context=` link (a launch context the research tools read) restores the chart,
 * draft and run it carried. `?study=` and `?compare=` open in the run history.
 */
import type { BacktestResearchLaunchContext, BacktestRunRecord } from "../backtest/backtestTypes.js";
import type { ChartStrategyCompletedRunConfig } from "../backtest/chart-tester/chartStrategyResultCache.js";
import { researchModeForTask, type StrategyResearchMode } from "./strategyResearchMode.js";
import { RESEARCH_SOURCE_SCHEMA, type ResearchSourceRefV1 } from "../research-data/researchDataTypes.js";

/** An imported dataset, selected once the library lists it. */
export interface DatasetChoice { datasetId: string; dataEpoch: string }

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

/**
 * The data a run used: its imported dataset, or the exchange history over its range (end exclusive).
 * Null when the run does not say (a forward run, an unknown market).
 */
export function researchRunSource(config: ChartStrategyCompletedRunConfig,
  run?: Pick<BacktestRunRecord, "dataset_id" | "data_epoch"> | null): ResearchSourceRefV1 | DatasetChoice | null {
  const exchange = text(config.exchange);
  const datasetId = text(run?.dataset_id) ?? text(config.dataset_id);
  const dataEpoch = text(run?.data_epoch) ?? text(config.data_epoch);
  if (exchange === "local" || (exchange === null && datasetId?.startsWith("local-"))) {
    return datasetId && dataEpoch ? { datasetId, dataEpoch } : null;
  }
  const marketType = text(config.market_type);
  const symbol = text(config.symbol);
  const interval = text(config.interval);
  if (!exchange || !marketType || !symbol || !interval) return null;
  return { schemaVersion: RESEARCH_SOURCE_SCHEMA, kind: "EXCHANGE_SERIES", exchange, marketType, symbol, interval,
    startMs: config.start_time_ms, endMs: config.end_time_ms + 1 };
}

/** What an older launch context opens in the workspace. */
export function launchContextState(context: BacktestResearchLaunchContext): {
  source: ResearchSourceRefV1 | DatasetChoice | null;
  draftId: string | null;
  runId: string | null;
  mode: StrategyResearchMode | null;
} {
  const session = context.chart_session;
  let source: ResearchSourceRefV1 | DatasetChoice | null = null;
  if (context.dataset_identity) {
    source = { datasetId: context.dataset_identity.dataset_id, dataEpoch: context.dataset_identity.data_epoch };
  } else if (context.source_workspace_id && context.source_cell_id && context.source_workspace_id !== "strategy-research") {
    // A chart cell: the workspace follows that chart, as a chart's hand-off does.
    source = { schemaVersion: RESEARCH_SOURCE_SCHEMA, kind: "CURRENT_CHART", workspaceId: context.source_workspace_id,
      cellId: context.source_cell_id, exchange: session.exchange, marketType: session.market_type, symbol: session.symbol,
      interval: session.interval };
  } else if (context.range.start_time_ms !== null && context.range.end_time_ms !== null) {
    source = { schemaVersion: RESEARCH_SOURCE_SCHEMA, kind: "EXCHANGE_SERIES", exchange: session.exchange,
      marketType: session.market_type, symbol: session.symbol, interval: session.interval,
      startMs: context.range.start_time_ms, endMs: context.range.end_time_ms + 1 };
  }
  return {
    source,
    draftId: text(context.strategy_draft_id),
    runId: text(context.latest_run_id),
    mode: context.entry_task ? researchModeForTask(context.entry_task) : null,
  };
}
