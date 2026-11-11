import { CHART_STRATEGY_TEMPLATES, type ChartStrategyTemplate } from "../backtest/chart-tester/chartStrategyTesterUiModel.js";
import { createChartStrategyDraftId } from "../backtest/chart-tester/chartStrategyTesterDrafts.js";
import type { StrategyDraftStore } from "../backtest/chart-tester/StrategyDraftStore.js";

export const RESEARCH_STRATEGY_TEMPLATES: readonly ChartStrategyTemplate[] = Object.freeze([
  ...CHART_STRATEGY_TEMPLATES,
  Object.freeze({
    id: "PINE_SAMPLED",
    nameKey: "chartTester.template.pineSample",
    descriptionKey: "chartTester.template.pineSampleDescription",
    displayName: "Pine Entry and Exit",
    language: "pine",
    source: `//@version=6
strategy("Sample entry and exit", overlay=true)
if bar_index == 0
    strategy.entry("L", strategy.long, qty=0.001)
if bar_index == 5
    strategy.close("L")
plot(close)
`,
  }),
]);

/** Save the strategy before choosing data, so navigation and refresh keep the user's choice. */
export async function saveResearchTemplate(store: StrategyDraftStore, templateId: string) {
  const template = RESEARCH_STRATEGY_TEMPLATES.find((item) => item.id === templateId);
  if (!template) throw new Error("Unknown strategy template");
  return store.save({
    id: createChartStrategyDraftId(),
    displayName: template.displayName,
    language: template.language,
    source: template.source,
    cursor: { line: 1, column: 1 },
  });
}
