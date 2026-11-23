export interface ChartStrategyTesterFlagEnvironment {
  VITE_CHART_STRATEGY_TESTER_ENABLED?: unknown;
  VITE_CHART_TRADE_EXPLANATION_ENABLED?: unknown;
  VITE_CHART_RUN_COMPARE_ENABLED?: unknown;
  VITE_CHART_STRATEGY_AUTO_RUN_ENABLED?: unknown;
  VITE_CHART_RUN_RESULT_VIEWS_ENABLED?: unknown;
  VITE_CHART_STRATEGY_FOLLOW_ENABLED?: unknown;
}

function strictEnabled(value: unknown): boolean {
  return value === true || value === 1 || value === "1";
}

function enabledByDefault(value: unknown): boolean {
  return value === undefined ? true : strictEnabled(value);
}

export function resolveChartStrategyTesterEnabled(
  environment: ChartStrategyTesterFlagEnvironment = {},
): boolean {
  return enabledByDefault(environment.VITE_CHART_STRATEGY_TESTER_ENABLED);
}

export function resolveChartTradeExplanationEnabled(
  environment: ChartStrategyTesterFlagEnvironment = {},
): boolean {
  return strictEnabled(environment.VITE_CHART_TRADE_EXPLANATION_ENABLED);
}

export function resolveChartRunCompareEnabled(
  environment: ChartStrategyTesterFlagEnvironment = {},
): boolean {
  return enabledByDefault(environment.VITE_CHART_RUN_COMPARE_ENABLED);
}

/**
 * Shared run-result views (ADR-BACKTEST-015 P1c). The ADR-013 visual review approved
 * them on 2026-11-21, so they default on; "0" restores the per-family views.
 */
export function resolveChartRunResultViewsEnabled(
  environment: ChartStrategyTesterFlagEnvironment = {},
): boolean {
  return enabledByDefault(environment.VITE_CHART_RUN_RESULT_VIEWS_ENABLED);
}

export function resolveChartStrategyAutoRunEnabled(
  environment: ChartStrategyTesterFlagEnvironment = {},
): boolean {
  return enabledByDefault(environment.VITE_CHART_STRATEGY_AUTO_RUN_ENABLED);
}

/**
 * ADR-BACKTEST-015 P4a: a native Pine run on the chart follows live bars by rebuilding its
 * latest prefix after each bar closes (O1). Off until its visual review; "1" turns it on.
 */
export function resolveChartStrategyFollowEnabled(
  environment: ChartStrategyTesterFlagEnvironment,
): boolean {
  return strictEnabled(environment.VITE_CHART_STRATEGY_FOLLOW_ENABLED);
}

function viteEnvironment(): ChartStrategyTesterFlagEnvironment {
  try {
    return {
      VITE_CHART_STRATEGY_TESTER_ENABLED:
        import.meta.env?.VITE_CHART_STRATEGY_TESTER_ENABLED,
      VITE_CHART_TRADE_EXPLANATION_ENABLED:
        import.meta.env?.VITE_CHART_TRADE_EXPLANATION_ENABLED,
      VITE_CHART_RUN_COMPARE_ENABLED:
        import.meta.env?.VITE_CHART_RUN_COMPARE_ENABLED,
      VITE_CHART_STRATEGY_AUTO_RUN_ENABLED:
        import.meta.env?.VITE_CHART_STRATEGY_AUTO_RUN_ENABLED,
      VITE_CHART_RUN_RESULT_VIEWS_ENABLED:
        import.meta.env?.VITE_CHART_RUN_RESULT_VIEWS_ENABLED,
      VITE_CHART_STRATEGY_FOLLOW_ENABLED:
        import.meta.env?.VITE_CHART_STRATEGY_FOLLOW_ENABLED,
    };
  } catch {
    return {};
  }
}

export const CHART_STRATEGY_TESTER_ENABLED = resolveChartStrategyTesterEnabled(
  viteEnvironment(),
);

export const CHART_TRADE_EXPLANATION_ENABLED = resolveChartTradeExplanationEnabled(
  viteEnvironment(),
);

export const CHART_RUN_COMPARE_ENABLED = resolveChartRunCompareEnabled(
  viteEnvironment(),
);

export const CHART_STRATEGY_AUTO_RUN_ENABLED = resolveChartStrategyAutoRunEnabled(
  viteEnvironment(),
);

export const CHART_RUN_RESULT_VIEWS_ENABLED = resolveChartRunResultViewsEnabled(
  viteEnvironment(),
);

export const CHART_STRATEGY_FOLLOW_ENABLED = resolveChartStrategyFollowEnabled(
  viteEnvironment(),
);
