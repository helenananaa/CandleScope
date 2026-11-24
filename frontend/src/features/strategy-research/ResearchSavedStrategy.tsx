import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";

import { Button, Field, InlineAlert, Select, Textarea } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import { describeError } from "../../i18n/serverErrors.js";
import { useLocale } from "../../i18n/useLocale.js";
import type { StrategyRunSettings } from "../../shared/strategyRunSettings.js";
import type { BacktestSnapshot, StrategyRevisionRecord } from "../backtest/backtestApi.js";
import { defaultParameters } from "../backtest/builtinTemplate.js";
import {
  persistPythonStudioState, pythonStudioPersisted, pythonStudioScope, restorePythonStudioState, restorePythonStudioStateFor,
  type PythonStudioGate,
} from "../backtest/pythonStudio.js";
import { parseResearchObjectJson } from "../backtest/research/backtestResearchAdvancedModel.js";
import type { LocalDatasetManifest } from "../local-data/localDataTypes.js";
import type { StrategyDataManager } from "../market-data/manager/strategyDataManager.js";
import { importedResearchRunSource } from "./importedDatasetSource.js";

const PythonStudioPanel = lazy(() => import("../backtest/PythonStudioPanel.js"));

type SavedManager = Pick<StrategyDataManager, "pythonStudioApi" | "savedPythonRevision" | "previewImportedBars" | "createBuiltinRsiRevision"
  | "startSavedRevision">;
type SavedKind = "bundle" | "builtin";

function errorText(reason: unknown): string {
  return reason instanceof Error ? describeError(reason, reason.message) : String(reason);
}

function plainParameters(value: Record<string, unknown>): Record<string, string | number | boolean> {
  return Object.fromEntries(Object.entries(value).filter((entry): entry is [string, string | number | boolean] =>
    ["string", "number", "boolean"].includes(typeof entry[1])));
}

/**
 * Saved strategies in the research workspace (ADR-BACKTEST-015 P5c4b): a multi-file Python bundle frozen
 * in the Python studio, or the builtin RSI (Wilder) template. Each is a strategy revision, not an editor
 * draft; it runs over the imported candles with the workspace's run settings, and the workspace shows the run.
 * The studio's gate is kept for the browser session: after a reload the frozen revision is loaded again by id
 * before the studio opens, and its smoke counts only when it passed on the same data and range.
 */
export function ResearchSavedStrategy({ manager, dataset, interval, settings, runBusy, onRunCreated }: {
  manager: SavedManager;
  dataset: LocalDatasetManifest;
  interval: string;
  settings: StrategyRunSettings;
  runBusy: boolean;
  onRunCreated(runId: string): void;
}) {
  useLocale();
  const [kind, setKind] = useState<SavedKind>("bundle");
  const [revisions, setRevisions] = useState<Partial<Record<SavedKind, StrategyRevisionRecord>>>({});
  const [parameterText, setParameterText] = useState<Partial<Record<SavedKind, string>>>({});
  const [outputModes, setOutputModes] = useState<Partial<Record<SavedKind, string>>>({});
  const [studio, setStudio] = useState<{ gate: PythonStudioGate; scope: string } | null>(null);
  const [snapshot, setSnapshot] = useState<BacktestSnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const studioApi = useMemo(() => manager.pythonStudioApi(), [manager]);
  const source = useMemo(() => {
    try {
      return importedResearchRunSource(dataset, { ...settings, fidelityPreference: "FAST" }, interval);
    } catch {
      return null;
    }
  }, [dataset, interval, settings]);
  const scope = source ? pythonStudioScope(source) : null;
  // The frozen revision a reload left behind; the studio opens once its record is loaded again.
  const [restoring, setRestoring] = useState<string | null>(() => restorePythonStudioState(true)?.revisionId ?? null);
  const accept = useCallback((target: SavedKind, next: StrategyRevisionRecord) => {
    setRevisions((current) => ({ ...current, [target]: next }));
    setParameterText((current) => ({ ...current, [target]: JSON.stringify(defaultParameters(next.parameter_schema), null, 2) }));
  }, []);
  useEffect(() => {
    if (!restoring) return;
    const controller = new AbortController();
    const done = () => { if (!controller.signal.aborted) setRestoring(null); };
    void manager.savedPythonRevision(restoring, controller.signal).then((found) => {
      if (found && !controller.signal.aborted) accept("bundle", found);
      done();
    }, (reason: unknown) => {
      if (!controller.signal.aborted) setError(errorText(reason));
      done();
    });
    return () => controller.abort();
  }, [accept, manager, restoring]);
  // The studio reports its gate under the data it was shown; a new range reports again, and the gate is saved as reported.
  const onGateChange = useCallback((gate: PythonStudioGate) => { if (scope) setStudio({ gate, scope }); }, [scope]);
  useEffect(() => {
    if (studio) persistPythonStudioState(true, pythonStudioPersisted(studio.gate, studio.scope));
  }, [studio]);
  const gate = studio?.gate ?? null;
  const bundleRevisionId = revisions.bundle?.revision_id ?? null;
  useEffect(() => {
    if (!source) return;
    const controller = new AbortController();
    void manager.previewImportedBars(source, controller.signal).then((value) => {
      if (!controller.signal.aborted) setSnapshot(value);
    }, (reason: unknown) => { if (!controller.signal.aborted) setError(errorText(reason)); });
    return () => controller.abort();
  }, [manager, source]);
  const revision = revisions[kind] ?? null;
  const text = parameterText[kind] ?? JSON.stringify(revision ? defaultParameters(revision.parameter_schema) : {}, null, 2);
  let parameters: Record<string, unknown> | null = null;
  try { parameters = parseResearchObjectJson(text, t("ux.parameters")); } catch { parameters = null; }
  const python = kind === "bundle";
  // Read when the studio opens: what it last saved, for the revision it will show.
  const restored = useMemo(() => {
    if (!python || !scope || restoring || !bundleRevisionId) return null;
    const saved = restorePythonStudioStateFor(scope);
    return saved?.revisionId === bundleRevisionId ? saved : null;
  }, [bundleRevisionId, python, restoring, scope]);
  const outputMode = revision && revision.output_modes.includes(outputModes[kind] ?? "") ? outputModes[kind]! : revision?.output_modes[0] ?? "";
  const ready = !!revision && !!parameters && !!source && (!python || (gate?.revisionId === revision.revision_id && gate.canCreateRun));
  return <section className="research-external-provider" data-testid="strategy-research-saved-strategy">
    <p className="research-panel-copy">{t("researchSaved.help")}</p>
    <Field label={t("researchSaved.kind")}>
      <Select size="sm" value={kind} disabled={busy} onChange={(event) => { setKind(event.target.value === "builtin" ? "builtin" : "bundle"); setError(null); }}>
        <option value="bundle">{t("researchSaved.bundle")}</option>
        <option value="builtin">{t("researchSaved.builtin")}</option>
      </Select>
    </Field>
    {python ? <Suspense fallback={<p className="research-empty">{t("research.strategy.pythonLoading")}</p>}>
      {restoring ? <p className="research-empty">{t("research.strategy.pythonLoading")}</p>
        : source && <PythonStudioPanel api={studioApi} loading={busy} snapshot={snapshot} datasetId={dataset.dataset_id}
          startTimeMs={source.startTimeMs} endTimeMs={source.endTimeMs} schemaParameters={plainParameters(parameters ?? {})}
          selectedRevisionId={bundleRevisionId ?? ""} restored={restored} onLoading={setBusy} onNotice={setNotice} onError={setError}
          onRevisionReady={(next) => accept("bundle", next)} onGateChange={onGateChange} />}
    </Suspense> : <div className="research-button-row">
      <Button size="sm" disabled={busy} onClick={() => {
        setBusy(true);
        setError(null);
        void manager.createBuiltinRsiRevision().then((next) => accept("builtin", next), (reason: unknown) => setError(errorText(reason))).finally(() => setBusy(false));
      }}>{t(revision ? "researchSaved.builtinReady" : "researchSaved.builtinCreate")}</Button>
    </div>}
    {revision && <>
      <p className="research-panel-copy" role="status">{t("researchSaved.revision", { name: revision.label, id: revision.revision_id })}</p>
      {revision.output_modes.length > 1 && <Field label={t("research.external.outputMode")}>
        <Select size="sm" value={outputMode} disabled={busy} onChange={(event) => setOutputModes((current) => ({ ...current, [kind]: event.target.value }))}>
          {revision.output_modes.map((value) => <option key={value} value={value}>{value}</option>)}
        </Select>
      </Field>}
      <Field label={t("ux.parameters")}>
        <Textarea className="research-json-editor" rows={4} spellCheck={false} value={text} disabled={busy}
          onChange={(event) => setParameterText((current) => ({ ...current, [kind]: event.target.value }))} />
      </Field>
      {!parameters && <InlineAlert tone="danger">{t("researchResult.invalidSettings")}</InlineAlert>}
      {python && !ready && <p className="research-empty">{t("researchSaved.needsSmoke")}</p>}
      <Button size="sm" variant="primary" disabled={busy || runBusy || !ready} onClick={() => {
        if (!revision || !parameters || !source) return;
        setBusy(true);
        setError(null);
        const length = Number(parameters.length);
        void manager.startSavedRevision({
          source, settings, revision, outputMode,
          parameters, ...(Number.isSafeInteger(length) && length > 0 ? { warmupBars: length + 1 } : {}),
          python: python && gate ? { runtimeMode: gate.runtimeMode, trustedConfirmed: gate.trustedConfirmed } : null,
        }).then((run) => onRunCreated(run.run_id), (reason: unknown) => setError(errorText(reason))).finally(() => setBusy(false));
      }}>{t("researchSaved.run")}</Button>
    </>}
    {notice && !error && <p className="research-panel-copy" role="status">{notice}</p>}
    {error && <InlineAlert tone="danger">{error}</InlineAlert>}
  </section>;
}
