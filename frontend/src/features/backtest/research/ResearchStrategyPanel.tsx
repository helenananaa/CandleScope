import { lazy, Suspense, useMemo, useState } from "react";
import { Button, Disclosure, Field, Input, Select, Textarea } from "../../../components/ui/index.js";
import { t } from "../../../i18n/index.js";
import { defaultBacktestApi } from "../backtestApi.js";
import { isPythonStrategyEntryEnabled } from "../backtestFlags.js";
import { restorePythonStudioState } from "../pythonStudio.js";
import type { BacktestResearchRuntime } from "./backtestResearchTypes.js";
import ResearchPanelFrame from "./ResearchPanelFrame.js";
import ResearchExternalProviderPanel from "./ResearchExternalProviderPanel.js";

const PythonStudioPanel = lazy(() => import("../PythonStudioPanel.js"));

function schemaParameters(runtime: BacktestResearchRuntime): Record<string, string | number | boolean> {
  const revision = runtime.view.revisions.find((item) => item.revision_id === runtime.view.selectedRevisionId);
  const values: Record<string, string | number | boolean> = {};
  for (const field of revision?.parameter_schema ?? []) {
    const name = typeof field.name === "string" ? field.name : "";
    const value = field.default;
    if (name && (typeof value === "string" || typeof value === "number" || typeof value === "boolean")) {
      values[name] = value;
    }
  }
  return { ...values, ...(runtime.view.launchContext?.parameters ?? {}) } as Record<string, string | number | boolean>;
}

export default function ResearchStrategyPanel({ runtime }: { runtime: BacktestResearchRuntime }) {
  const {
    advancedEnabled,
    draft,
    revisions,
    selectedRevisionId,
    selectedTask,
    snapshot,
    selectedDatasetId,
    startTimeMs,
    endTimeMs,
    busy,
  } = runtime.view;
  const [revisionName, setRevisionName] = useState("Research revision");
  const [revisionLanguage, setRevisionLanguage] = useState("BUILTIN_TEMPLATE");
  const [revisionSource, setRevisionSource] = useState("");
  const parameters = useMemo(() => schemaParameters(runtime), [runtime]);
  const pythonEnabled = isPythonStrategyEntryEnabled();
  const restoredStudio = useMemo(() => restorePythonStudioState(pythonEnabled), [pythonEnabled]);
  return (
    <ResearchPanelFrame
      eyebrow={t("research.panel.strategy")}
      title={draft?.displayName ?? selectedRevisionId ?? t("research.strategy.noDraft")}
    >
      {draft && (
        <dl className="research-facts">
          <div><dt>{t("research.strategy.draft")}</dt><dd>{draft.id}</dd></div>
          <div><dt>{t("research.strategy.language")}</dt><dd>{draft.language}</dd></div>
          <div><dt>{t("research.strategy.parameters")}</dt><dd>{Object.keys(runtime.view.launchContext?.parameters ?? {}).length}</dd></div>
        </dl>
      )}
      {advancedEnabled ? (
        <>
          <Field label={t("research.strategy.revision")}>
            <Select size="sm" value={selectedRevisionId} onChange={(event) => runtime.actions.selectRevision(event.target.value)}>
              {revisions.map((revision) => <option key={revision.revision_id} value={revision.revision_id}>{revision.label}</option>)}
            </Select>
          </Field>
          <div className="research-button-row">
            <Button size="sm" disabled={busy || !snapshot} onClick={() => void runtime.actions.smokeStrategyRevision()}>{t("research.strategy.smoke")}</Button>
            <Button size="sm" variant="ghost" disabled={busy || !selectedRevisionId} onClick={() => void runtime.actions.copyStrategyRevision()}>{t("research.strategy.copy")}</Button>
            <Button size="sm" variant="ghost" disabled={busy || !selectedRevisionId} onClick={() => void runtime.actions.archiveStrategyRevision()}>{t("research.strategy.archive")}</Button>
          </div>
          <ResearchExternalProviderPanel runtime={runtime} />
          <Disclosure summary={t("research.strategy.create")}>
            <div className="research-form">
              <Field label={t("research.strategy.name")}><Input size="sm" value={revisionName} onChange={(event) => setRevisionName(event.target.value)} /></Field>
              <Field label={t("research.strategy.language")}>
                <Select size="sm" value={revisionLanguage} onChange={(event) => setRevisionLanguage(event.target.value)}>
                  <option value="BUILTIN_TEMPLATE">{t("research.strategy.template")}</option>
                  <option value="PINE">{t("research.strategy.pine")}</option>
                  {runtime.view.capabilities?.flags.BACKTEST_EXTERNAL_PROVIDER_ENABLED && <option value="EXTERNAL_PROVIDER">{t("research.external.title")}</option>}
                </Select>
              </Field>
              <Field label={t(revisionLanguage === "EXTERNAL_PROVIDER" ? "research.external.manifest" : "research.strategy.source")}>
                <Textarea className="research-json-editor" rows={6} spellCheck={false} value={revisionSource} onChange={(event) => setRevisionSource(event.target.value)} />
              </Field>
              <Button size="sm" variant="primary" disabled={busy || !revisionName.trim()} onClick={() => void runtime.actions.createStrategyRevision({
                name: revisionName,
                language: revisionLanguage,
                base_revision_id: revisionLanguage === "BUILTIN_TEMPLATE" ? "builtin-rsi-wilder-long-short-v1" : null,
                source_text: revisionSource,
                parameter_schema: revisionLanguage === "BUILTIN_TEMPLATE" ? [
                  { name: "length", type: "integer", default: 24, minimum: 2 },
                  { name: "oversold", type: "number", default: 30 },
                  { name: "overbought", type: "number", default: 70 },
                ] : [],
              })}>{t("research.strategy.compile")}</Button>
            </div>
          </Disclosure>
          {selectedTask === "PYTHON_MODEL" && (
            <Disclosure defaultOpen summary={t("research.strategy.pythonTitle")}>
              {pythonEnabled ? (
                <Suspense fallback={<p className="research-empty">{t("research.strategy.pythonLoading")}</p>}>
                  <PythonStudioPanel
                    api={defaultBacktestApi}
                    loading={busy}
                    snapshot={snapshot}
                    datasetId={selectedDatasetId}
                    startTimeMs={startTimeMs}
                    endTimeMs={endTimeMs}
                    schemaParameters={parameters}
                    selectedRevisionId={selectedRevisionId}
                    {...(restoredStudio === null ? {} : {
                      restored: {
                        revisionId: restoredStudio.revisionId,
                        bundleIdentity: restoredStudio.bundleIdentity,
                        smokePassed: restoredStudio.smokePassed,
                        runtimeMode: restoredStudio.runtimeMode,
                        trustedConfirmed: restoredStudio.trustedConfirmed,
                      },
                    })}
                    onLoading={runtime.actions.setBusy}
                    onNotice={runtime.actions.setNotice}
                    onError={runtime.actions.setOperationError}
                    onRevisionReady={(revision) => runtime.actions.acceptStrategyRevision(revision)}
                    onGateChange={runtime.actions.setPythonGate}
                  />
                </Suspense>
              ) : <p className="research-empty">{t("research.strategy.pythonDisabled")}</p>}
            </Disclosure>
          )}
        </>
      ) : (
        <Disclosure summary={`${t("research.strategy.revisions")} · ${revisions.length}`}>
          <ul className="research-row-list">
            {revisions.slice(0, 10).map((revision) => (
              <li key={revision.revision_id} className="research-row" data-active={revision.revision_id === selectedRevisionId}>
                <span><strong>{revision.label}</strong><small>{revision.revision_id}</small></span>
              </li>
            ))}
          </ul>
        </Disclosure>
      )}
    </ResearchPanelFrame>
  );
}
