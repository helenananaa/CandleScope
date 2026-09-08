import { useEffect, useState } from "react";
import { t } from "../../i18n/index.js";
import { CHART_STRATEGY_TEMPLATES } from "../backtest/chart-tester/chartStrategyTesterUiModel.js";
import { getChartStrategyDraftStore } from "../backtest/chart-tester/chartStrategyTesterDrafts.js";
import type { StrategyDraftRecord } from "../backtest/chart-tester/StrategyDraftStore.js";

export function StrategyResearchFirstOpen({
  libraryEnabled,
  runtimeMode,
  onOpenLibrary,
  draftId,
  saving,
  onSelectTemplate,
}: {
  libraryEnabled: boolean;
  runtimeMode: "LIVE" | "LOCAL_OFFLINE";
  onOpenLibrary(): void;
  draftId: string | null;
  saving: boolean;
  onSelectTemplate(templateId: string): void;
}) {
  const [draft, setDraft] = useState<StrategyDraftRecord | null>(null);
  useEffect(() => {
    let cancelled = false;
    if (draftId !== null) {
      void getChartStrategyDraftStore().load(draftId).then((view) => {
        if (!cancelled) setDraft(view.record);
      });
    }
    return () => { cancelled = true; };
  }, [draftId]);
  const selected = draft?.id === draftId ? draft : null;
  return (
    <div className="strategy-research-first-open" data-testid="strategy-research-first-open" data-strategy-draft={draftId ?? ""}>
      <p className="chart-strategy-eyebrow">{t("chartTester.startEyebrow")}</p>
      <h2>{t("chartTester.startTitle")}</h2>
      <p>{t("strategy.firstOpenLead")}</p>
      {selected && (
        <div className="strategy-research-resume" role="status">
          <div><small>{t("chartTester.autosave.saved")}</small><strong>{selected.displayName}</strong></div>
          <button type="button" className="research-primary" onClick={onOpenLibrary}>{t("research.source.openLibrary")}</button>
        </div>
      )}
      <div className="strategy-research-templates" data-testid="strategy-research-templates">
        {CHART_STRATEGY_TEMPLATES.map((template) => (
          <button
            key={template.id}
            type="button"
            data-testid={`strategy-research-template-${template.id}`}
            disabled={!libraryEnabled || saving}
            aria-pressed={selected?.source === template.source}
            onClick={() => onSelectTemplate(template.id)}
          >
            <strong>{t(template.nameKey)}</strong>
            <span>{t(template.descriptionKey)}</span>
            <small>{t("chartTester.language.pyne")}</small>
          </button>
        ))}
      </div>
      {saving && <p role="status">{t("chartTester.autosave.saving")}</p>}
      <div className="strategy-research-first-open-actions">
        <div data-testid="strategy-research-current-chart-unavailable">
          <p>
            {runtimeMode === "LOCAL_OFFLINE"
              ? t("research.source.offlineLiveUnavailable")
              : t("strategy.currentChartUnbound")}
          </p>
          {runtimeMode === "LIVE" ? (
            <a href="/" data-testid="strategy-research-open-market-tester">
              {t("strategy.openMarketTester")}
            </a>
          ) : null}
        </div>
        {libraryEnabled ? (
          <button type="button" data-testid="strategy-research-import-own-data" onClick={onOpenLibrary}>
            {t("research.source.openLibrary")}
          </button>
        ) : null}
      </div>
    </div>
  );
}
