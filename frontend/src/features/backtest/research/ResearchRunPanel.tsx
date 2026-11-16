import { useMemo, useState } from "react";
import { Badge, Button, Disclosure, Field, InlineAlert, Input, Select } from "../../../components/ui/index.js";
import { t } from "../../../i18n/index.js";
import { researchStateTone } from "./researchStateTone.js";
import { parseResearchRunConfig, researchRunIsActive } from "./backtestResearchAdvancedModel.js";
import type { BacktestResearchRuntime } from "./backtestResearchTypes.js";
import ResearchPanelFrame from "./ResearchPanelFrame.js";

export default function ResearchRunPanel({ runtime }: { runtime: BacktestResearchRuntime }) {
  const { advancedEnabled, activeRun, runs, busy } = runtime.view;
  const [compareRunId, setCompareRunId] = useState("");
  const [cloneParameter, setCloneParameter] = useState("");
  const [cloneValue, setCloneValue] = useState("25");
  const compareOptions = useMemo(
    () => runs.filter((run) => run.run_id !== activeRun?.run_id && run.state === "COMPLETED"),
    [activeRun?.run_id, runs],
  );
  const cloneParameters = useMemo(
    () => {
      const parameters = parseResearchRunConfig(activeRun).parameters;
      return parameters && typeof parameters === "object" && !Array.isArray(parameters)
        ? Object.keys(parameters).sort()
        : [];
    },
    [activeRun],
  );
  const selectedCloneParameter = cloneParameters.includes(cloneParameter)
    ? cloneParameter
    : cloneParameters[0] ?? "";
  const parseCloneValue = () => Number.isFinite(Number(cloneValue)) ? Number(cloneValue) : cloneValue;
  return (
    <ResearchPanelFrame eyebrow={t("research.panel.run")} title={activeRun?.run_id ?? t("research.run.none")}>
      {activeRun && (
        <div className="research-active-run">
          <Badge tone={researchStateTone(activeRun.state)}>{activeRun.state}</Badge>
          <small>{activeRun.fidelity_mode}</small>
        </div>
      )}
      {activeRun?.waiting_for && <InlineAlert tone="warning">{t(activeRun.waiting_for === "EXTERNAL_PROVIDER_DISABLED"
        ? "research.external.disabledRun" : activeRun.waiting_for === "EXTERNAL_CONNECTION_REVOKED"
          ? "research.external.revokedRun" : "research.external.waitingRun")}</InlineAlert>}
      {advancedEnabled && (
        <>
          <div className="research-button-row">
            <Button size="sm" disabled={busy || !activeRun || !researchRunIsActive(activeRun)} onClick={() => void runtime.actions.cancelRun()}>{t("research.run.cancel")}</Button>
            <Button size="sm" disabled={busy || !activeRun} onClick={() => void runtime.actions.resumeRun()}>{t("research.run.resume")}</Button>
            <Button size="sm" variant="ghost" disabled={busy || !activeRun} onClick={() => void runtime.actions.exportRun()}>{t("research.run.export")}</Button>
          </div>
          <Disclosure summary={t("research.run.cloneSummary")}>
            <div className="research-form">
              {cloneParameters.length > 0
                ? <Field label={t("research.run.parameter")}><Select size="sm" value={selectedCloneParameter} onChange={(event) => setCloneParameter(event.target.value)}>{cloneParameters.map((parameter) => <option value={parameter} key={parameter}>{parameter}</option>)}</Select></Field>
                : <p className="research-empty">{t("research.run.noCloneParameters")}</p>}
              <Field label={t("research.run.value")}><Input size="sm" value={cloneValue} onChange={(event) => setCloneValue(event.target.value)} /></Field>
              <Button size="sm" disabled={busy || !activeRun || !selectedCloneParameter} onClick={() => void runtime.actions.cloneRun(selectedCloneParameter, parseCloneValue())}>{t("research.run.clone")}</Button>
            </div>
          </Disclosure>
          <Disclosure summary={t("research.run.compareSummary")}>
            <div className="research-form">
              <Field label={t("research.run.baseline")}><Select size="sm" value={compareRunId} onChange={(event) => setCompareRunId(event.target.value)}><option value="">{t("research.run.select")}</option>{compareOptions.map((run) => <option value={run.run_id} key={run.run_id}>{run.run_id}</option>)}</Select></Field>
              <Button size="sm" disabled={busy || !activeRun || !compareRunId} onClick={() => void runtime.actions.compareRun(compareRunId)}>{t("research.run.compare")}</Button>
            </div>
          </Disclosure>
        </>
      )}
      <ul className="research-row-list">
        {runs.slice(0, 20).map((run) => (
          <li key={run.run_id}>
            <button
              type="button"
              className="research-row"
              data-active={run.run_id === activeRun?.run_id}
              aria-current={run.run_id === activeRun?.run_id ? "true" : undefined}
              onClick={() => void runtime.actions.openRun(run.run_id)}
            >
              <span><strong>{run.run_id}</strong><small>{run.fidelity_mode}</small></span>
              <Badge tone={researchStateTone(run.state)}>{run.state}</Badge>
            </button>
          </li>
        ))}
      </ul>
    </ResearchPanelFrame>
  );
}
