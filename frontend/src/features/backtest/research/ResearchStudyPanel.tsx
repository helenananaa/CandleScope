import { Badge, Button, Disclosure, InlineAlert, Textarea } from "../../../components/ui/index.js";
import { t } from "../../../i18n/index.js";
import { researchStateTone } from "./researchStateTone.js";
import { researchStudyIsActive } from "./backtestResearchAdvancedModel.js";
import type { BacktestResearchRuntime } from "./backtestResearchTypes.js";
import ResearchPanelFrame from "./ResearchPanelFrame.js";

export default function ResearchStudyPanel({ runtime }: { runtime: BacktestResearchRuntime }) {
  const { advancedEnabled, activeStudy, studies, studyDraftText, studyComparison, busy, revisions, selectedRevisionId } = runtime.view;
  const holdoutCanReveal = activeStudy?.state === "AWAITING_HOLDOUT" && activeStudy.holdout?.state === "SEALED";
  const selectedRevision = revisions.find((revision) => revision.revision_id === selectedRevisionId);
  const studyCompatible = selectedRevision?.output_modes.includes("SIGNAL") === true;
  const contractReady = (runtime.view.snapshot?.quality.contract_data as Record<string, unknown> | undefined)?.status === "complete";
  return (
    <ResearchPanelFrame eyebrow={t("research.panel.study")} title={activeStudy?.name ?? t("research.study.none")}>
      <p className="research-panel-copy">{t("research.study.draftHint")}</p>
      {advancedEnabled && (
        <>
          <Disclosure defaultOpen summary={t("research.study.draftSummary")}>
            {!studyCompatible && <InlineAlert tone="danger">{t("research.study.incompatible")}</InlineAlert>}
            {studyCompatible && !contractReady && <InlineAlert tone="danger">{t("research.study.dataIncompatible")}</InlineAlert>}
            <Textarea className="research-json-editor" aria-label={t("research.study.draftAria")} rows={16} spellCheck={false} value={studyDraftText} onChange={(event) => runtime.actions.setStudyDraftText(event.target.value)} />
            <div className="research-button-row">
              <Button size="sm" variant="ghost" disabled={busy} onClick={runtime.actions.resetStudyDraft}>{t("research.study.reset")}</Button>
              <Button size="sm" variant="primary" disabled={busy || !runtime.view.snapshot || !runtime.view.selectedRevisionId || !studyCompatible || !contractReady} onClick={() => void runtime.actions.createStudy()}>{t("research.study.create")}</Button>
            </div>
          </Disclosure>
          <div className="research-button-row">
            <Button size="sm" variant="primary" disabled={busy || activeStudy?.state !== "CREATED" || !contractReady} onClick={() => void runtime.actions.startStudy()}>{t("research.study.start")}</Button>
            <Button size="sm" disabled={busy || !activeStudy || !researchStudyIsActive(activeStudy.state)} onClick={() => void runtime.actions.cancelStudy()}>{t("research.study.cancel")}</Button>
            <Button size="sm" disabled={busy || !holdoutCanReveal} onClick={() => void runtime.actions.revealStudyHoldout()}>{t("research.study.reveal")}</Button>
            <Button size="sm" disabled={busy || !activeStudy} onClick={() => void runtime.actions.compareStudy()}>{t("research.study.compare")}</Button>
          </div>
        </>
      )}
      <ul className="research-row-list">
        {studies.slice(0, 20).map((study) => (
          <li key={study.study_id}>
            <button
              type="button"
              className="research-row"
              data-active={study.study_id === activeStudy?.study_id}
              aria-current={study.study_id === activeStudy?.study_id ? "true" : undefined}
              onClick={() => void runtime.actions.openStudy(study.study_id)}
            >
              <span><strong>{study.name}</strong><small>{study.study_id}</small></span>
              <Badge tone={researchStateTone(study.state)}>{study.state}</Badge>
            </button>
          </li>
        ))}
      </ul>
      {activeStudy && (
        <Disclosure summary={t("research.study.authority")}>
          <pre className="research-json-readout">{JSON.stringify({
            protocol: activeStudy.study_protocol_revision,
            identity: activeStudy.identity,
            holdout: activeStudy.holdout,
            folds: activeStudy.folds,
            oos_report: activeStudy.oos_report,
            dataset_basket: activeStudy.dataset_basket,
          }, null, 2)}</pre>
        </Disclosure>
      )}
      {studyComparison && (
        <Disclosure defaultOpen summary={t("research.study.oos", { count: studyComparison.completed_trial_count })}>
          <pre className="research-json-readout">{JSON.stringify({
            ready: studyComparison.ready,
            selection_warning: studyComparison.selection_warning,
            ranking: studyComparison.ranking,
            independent_symbol_robustness: studyComparison.independent_symbol_robustness,
            portfolio_sum_forbidden: studyComparison.portfolio_sum_forbidden,
          }, null, 2)}</pre>
        </Disclosure>
      )}
    </ResearchPanelFrame>
  );
}
