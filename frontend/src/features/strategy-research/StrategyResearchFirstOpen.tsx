import { useEffect, useState } from "react";
import { Button, buttonClassName } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import { strategyLanguageLabel } from "../backtest/chart-tester/strategyLanguageLabel.js";
import { RESEARCH_STRATEGY_TEMPLATES } from "./strategyTemplateDraft.js";
import { getChartStrategyDraftStore } from "../backtest/chart-tester/chartStrategyTesterDrafts.js";
import type { StrategyDraftRecord } from "../backtest/chart-tester/StrategyDraftStore.js";

export function StrategyResearchFirstOpen({
  runtimeMode,
  onOpenLibrary,
  draftId,
  saving,
  onSelectTemplate,
}: {
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
      <header className="strategy-research-first-open-head">
        <h2>{t("chartTester.startTitle")}</h2>
        <p>{t("strategy.firstOpenLead")}</p>
      </header>
      {selected && (
        <div className="strategy-research-resume" role="status">
          <div><small>{t("chartTester.autosave.saved")}</small><strong>{selected.displayName}</strong></div>
          <Button variant="primary" size="sm" onClick={onOpenLibrary}>{t("research.source.openLibrary")}</Button>
        </div>
      )}
      <div className="strategy-research-templates" data-testid="strategy-research-templates">
        {RESEARCH_STRATEGY_TEMPLATES.map((template) => (
          <button
            key={template.id}
            type="button"
            className="strategy-template-card"
            data-testid={`strategy-research-template-${template.id}`}
            disabled={saving}
            aria-pressed={selected?.source === template.source}
            onClick={() => onSelectTemplate(template.id)}
          >
            <strong>{t(template.nameKey)}</strong>
            <span>{t(template.descriptionKey)}</span>
            <small>{strategyLanguageLabel(template.language)}</small>
          </button>
        ))}
      </div>
      {saving && <p className="strategy-research-note" role="status">{t("chartTester.autosave.saving")}</p>}
      <div className="strategy-research-first-open-actions" data-testid="strategy-research-current-chart-unavailable">
        <p>
          {runtimeMode === "LOCAL_OFFLINE"
            ? t("research.source.offlineLiveUnavailable")
            : t("strategy.currentChartUnbound")}
        </p>
        <div className="strategy-research-first-open-buttons">
          {runtimeMode === "LIVE" ? (
            <a href="/" className={buttonClassName({ variant: "ghost" })} data-testid="strategy-research-open-market-tester">
              {t("strategy.openMarketTester")}
            </a>
          ) : null}
          <Button data-testid="strategy-research-import-own-data" onClick={onOpenLibrary}>
            {t("research.source.openLibrary")}
          </Button>
        </div>
      </div>
    </div>
  );
}
