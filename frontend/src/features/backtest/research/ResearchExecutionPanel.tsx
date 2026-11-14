import { useState } from "react";
import { Badge, Button, Disclosure, Textarea } from "../../../components/ui/index.js";
import { researchStateTone } from "./researchStateTone.js";
import { t } from "../../../i18n/index.js";
import type { BacktestResearchRuntime } from "./backtestResearchTypes.js";
import ResearchPanelFrame from "./ResearchPanelFrame.js";
import ResearchChartBookInputs from "./ResearchChartBookInputs.js";
import { parseResearchObjectJson } from "./backtestResearchAdvancedModel.js";

export default function ResearchExecutionPanel({ runtime }: { runtime: BacktestResearchRuntime }) {
  const [importing, setImporting] = useState(false);
  const { advancedEnabled, selectedTask, activeRun, launchContext, runDraftText, busy } = runtime.view;
  let fidelity = activeRun?.fidelity_mode ?? "BAR_APPROX";
  if (!activeRun) {
    try { fidelity = String(parseResearchObjectJson(runDraftText, "Run draft").fidelity_mode ?? fidelity); } catch { /* unfinished draft */ }
  }
  const copy = selectedTask === "PRECISE_EXECUTION"
    ? t("research.execution.precise")
    : selectedTask === "PYTHON_MODEL"
      ? t("research.execution.python")
      : t("research.execution.general");
  return (
    <ResearchPanelFrame eyebrow={t("research.panel.execution")} title={fidelity}>
      <p className="research-panel-copy">{copy}</p>
      <dl className="research-facts">
        <div><dt>{t("research.execution.preset")}</dt><dd>{launchContext?.quick_preset_id ?? "—"}</dd></div>
        <div><dt>{t("research.execution.state")}</dt><dd><Badge tone={researchStateTone(activeRun?.state ?? "DRAFT")}>{activeRun?.state ?? "DRAFT"}</Badge></dd></div>
        <div><dt>{t("research.execution.configHash")}</dt><dd title={activeRun?.config_hash}>{activeRun?.config_hash?.slice(0, 16) ?? "—"}</dd></div>
      </dl>
      <ResearchChartBookInputs runtime={runtime} onLoadingChange={setImporting} />
      {advancedEnabled && (
        <Disclosure defaultOpen summary={t("research.execution.draft")}>
          <p className="research-panel-copy">{t("research.execution.authority")}</p>
          <Textarea
            className="research-json-editor"
            disabled={busy || importing}
            aria-label={t("research.execution.configAria")}
            rows={18}
            spellCheck={false}
            value={runDraftText}
            onChange={(event) => runtime.actions.setRunDraftText(event.target.value)}
          />
          <div className="research-button-row">
            <Button size="sm" variant="ghost" disabled={busy} onClick={runtime.actions.resetRunDraft}>{t("research.execution.reset")}</Button>
            <Button size="sm" variant="primary" disabled={busy || importing || !runtime.view.snapshot || !runtime.view.selectedRevisionId} onClick={() => void runtime.actions.createRun()}>{t("research.execution.create")}</Button>
          </div>
        </Disclosure>
      )}
    </ResearchPanelFrame>
  );
}
