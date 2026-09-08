import { CHART_STRATEGY_TEMPLATES } from "../backtest/chart-tester/chartStrategyTesterUiModel.js";
import { createChartStrategyDraftId } from "../backtest/chart-tester/chartStrategyTesterDrafts.js";
import type { StrategyDraftStore } from "../backtest/chart-tester/StrategyDraftStore.js";

/** Save the strategy before choosing data, so navigation and refresh keep the user's choice. */
export async function saveResearchTemplate(store: StrategyDraftStore, templateId: string) {
  const template = CHART_STRATEGY_TEMPLATES.find((item) => item.id === templateId);
  if (!template) throw new Error("Unknown strategy template");
  return store.save({
    id: createChartStrategyDraftId(),
    displayName: template.displayName,
    language: template.language,
    source: template.source,
    cursor: { line: 1, column: 1 },
  });
}
