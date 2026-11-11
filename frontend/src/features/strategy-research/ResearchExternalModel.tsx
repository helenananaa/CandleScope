import { useEffect, useRef, useState } from "react";

import { t } from "../../i18n/index.js";
import { describeError } from "../../i18n/serverErrors.js";
import type { StrategyRunSettings } from "../../shared/strategyRunSettings.js";
import type { ExternalProviderConnection, StrategyRevisionRecord } from "../backtest/backtestApi.js";
import type { BacktestRunRecord } from "../backtest/backtestTypes.js";
import { parseResearchObjectJson, parseResearchRunConfig } from "../backtest/research/backtestResearchAdvancedModel.js";
import type { LocalDatasetManifest } from "../local-data/localDataTypes.js";
import type { StrategyDataManager } from "../market-data/manager/strategyDataManager.js";
import { importedResearchRunSource } from "./importedDatasetSource.js";

type PreparedModel = Awaited<ReturnType<StrategyDataManager["prepareExternalModel"]>>;
type ModelSelection = { revisionId: string; parameters: string; outputMode: string; connectionId: string };
const initialSelection: ModelSelection = { revisionId: "", parameters: "{}", outputMode: "", connectionId: "" };

function savedModelSelection(run: BacktestRunRecord | null, dataset: LocalDatasetManifest, interval: string): ModelSelection {
  if (!run || run.dataset_id !== dataset.dataset_id || run.data_epoch !== dataset.data_epoch) return initialSelection;
  const config = parseResearchRunConfig(run);
  if (config.interval !== interval || typeof config.external_connection_id !== "string" || typeof config.strategy_revision_id !== "string") {
    return initialSelection;
  }
  return {
    revisionId: config.strategy_revision_id,
    parameters: JSON.stringify(config.parameters ?? {}, null, 2),
    outputMode: typeof config.output_mode === "string" ? config.output_mode : "",
    connectionId: config.external_connection_id,
  };
}

function errorText(reason: unknown): string {
  return reason instanceof Error ? describeError(reason, reason.message) : String(reason);
}

export function ResearchExternalModel({ manager, dataset, interval, settings, savedRun, active, runBusy, onRunCreated }: {
  manager: StrategyDataManager;
  dataset: LocalDatasetManifest;
  interval: string;
  settings: StrategyRunSettings;
  savedRun: BacktestRunRecord | null;
  active: boolean;
  runBusy: boolean;
  onRunCreated(runId: string): void;
}) {
  const [revisions, setRevisions] = useState<StrategyRevisionRecord[] | null>();
  const [selection, setSelection] = useState<ModelSelection | null>(null);
  const { revisionId, parameters, outputMode, connectionId } = selection ?? savedModelSelection(savedRun, dataset, interval);
  const [draft, setDraft] = useState<{ model: PreparedModel; settings: StrategyRunSettings } | null>(null);
  const [connections, setConnections] = useState<ExternalProviderConnection[]>([]);
  const [refresh, setRefresh] = useState(0);
  const [name, setName] = useState("");
  const [manifest, setManifest] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bindingError, setBindingError] = useState<string | null>(null);
  const action = useRef<AbortController | null>(null);
  useEffect(() => () => action.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    void manager.externalModelRevisions(controller.signal).then(rows => {
      if (!controller.signal.aborted) setRevisions(rows);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(errorText(reason));
    });
    return () => controller.abort();
  }, [manager]);

  const revision = revisions?.find(row => row.revision_id === revisionId) ?? revisions?.[0];
  const mode = revision?.output_modes.includes(outputMode) ? outputMode : revision?.output_modes[0];

  useEffect(() => {
    if (!revision || !mode) return;
    const controller = new AbortController();
    const prepare = async () => {
      const source = importedResearchRunSource(dataset, { ...settings, fidelityPreference: settings.fidelityPreference ?? "FAST" }, interval);
      return manager.prepareExternalModel({ source, settings, revision, outputMode: mode }, controller.signal);
    };
    void prepare().then(prepared => {
      if (!controller.signal.aborted) {
        setBindingError(null);
        setDraft({ model: prepared, settings });
      }
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setBindingError(errorText(reason));
    });
    return () => controller.abort();
  }, [dataset, interval, manager, mode, revision, settings]);

  const prepared = draft?.settings === settings && draft.model.revision === revision && draft.model.body.output_mode === mode ? draft.model : null;
  useEffect(() => {
    if (!active || !prepared) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const list = async () => {
      try {
        const next = await manager.externalModelConnections(prepared, controller.signal);
        if (!controller.signal.aborted) {
          setConnections(next);
          setBindingError(null);
        }
      } catch (reason) {
        if (!controller.signal.aborted) setBindingError(errorText(reason));
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(() => void list(), 2000);
      }
    };
    void list();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [active, manager, prepared, refresh]);

  async function perform(operation: (signal: AbortSignal) => Promise<void>) {
    if (action.current !== null) return;
    const controller = new AbortController();
    action.current = controller;
    setBusy(true);
    setError(null);
    try {
      await operation(controller.signal);
    } catch (reason) {
      if (!controller.signal.aborted) setError(errorText(reason));
    } finally {
      action.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  function register(input: { name: string; manifestText: string } | null) {
    void perform(async signal => {
      const saved = await manager.registerExternalModel(input ? {
        name: input.name,
        manifest: parseResearchObjectJson(input.manifestText, t("research.external.manifest")),
      } : null, signal);
      signal.throwIfAborted();
      setRevisions(current => [saved, ...(current ?? []).filter(row => row.revision_id !== saved.revision_id)]);
      selectRevision(saved.revision_id);
    });
  }

  function selectRevision(id: string) {
    setDraft(null);
    setConnections([]);
    setBindingError(null);
    setSelection({ ...initialSelection, revisionId: id });
  }

  function changeSelection(next: Partial<ModelSelection>) {
    setSelection(current => ({ ...(current ?? savedModelSelection(savedRun, dataset, interval)), ...next }));
  }

  if (revisions === null) return <p>{t("research.external.disabled")}</p>;
  if (revisions === undefined) return error ? <p role="alert">{error}</p> : <p role="status">{t("research.loading")}</p>;

  const matching = prepared ? connections.filter(connection => connection.scope.snapshot_hash === prepared.body.snapshot_hash
    && connection.scope.strategy_revision_id === revision?.revision_id) : [];
  const connection = matching.find(row => row.connection_id === connectionId) ?? matching[0];
  const provider = revision?.external_provider;
  return <section className="research-external-provider" data-testid="strategy-research-external-model">
    <p>{t("research.external.boundary")}</p>
    <button type="button" disabled={busy} onClick={() => register(null)}>{t("research.external.registerExample")}</button>
    <details>
      <summary>{t("research.external.manifest")}</summary>
      <label className="research-field">{t("research.strategy.name")}<input value={name} maxLength={128} disabled={busy} onChange={event => setName(event.target.value)} /></label>
      <label className="research-field">{t("research.external.manifest")}<textarea rows={5} value={manifest} maxLength={16000} disabled={busy} onChange={event => setManifest(event.target.value)} /></label>
      <button type="button" disabled={busy || !name.trim() || !manifest.trim()} onClick={() => register({ name: name.trim(), manifestText: manifest })}>
        {t("research.external.registerManifest")}
      </button>
    </details>
    {revision && <>
      <label className="research-field">{t("research.external.model")}
        <select value={revision.revision_id} disabled={busy} onChange={event => selectRevision(event.target.value)}>
          {revisions.map(row => <option key={row.revision_id} value={row.revision_id}>{row.label} · {row.external_provider?.provider_revision}</option>)}
        </select>
      </label>
      <p>{t("research.external.artifact")} · <code>{provider?.artifact_sha256}</code></p>
      <p>{t("research.external.dataset")} · {dataset.name} · {interval}</p>
      {prepared && <p>{t("research.external.snapshot", { epoch: dataset.data_epoch })}</p>}
      <label className="research-field">{t("research.external.outputMode")}
        <select value={mode} disabled={busy} onChange={event => { setDraft(null); changeSelection({ outputMode: event.target.value }); }}>
          {revision.output_modes.map(value => <option key={value}>{value}</option>)}
        </select>
      </label>
      <label className="research-field">{t("ux.parameters")}
        <textarea value={parameters} maxLength={16000} rows={3} disabled={busy} onChange={event => changeSelection({ parameters: event.target.value })} />
      </label>
      <div className="research-button-row">
        <button type="button" disabled={busy || !prepared} onClick={() => prepared && void perform(async signal => {
          const created = await manager.createExternalModelConnection(prepared, signal);
          signal.throwIfAborted();
          setConnections(current => [created, ...current.filter(row => row.connection_id !== created.connection_id)]);
          changeSelection({ connectionId: created.connection_id });
          setRefresh(value => value + 1);
        })}>{t("research.external.create")}</button>
        <button type="button" disabled={busy || !connection} onClick={() => connection && void perform(async signal => {
          await manager.revokeExternalModelConnection(connection.connection_id, signal);
          signal.throwIfAborted();
          setConnections(current => current.filter(row => row.connection_id !== connection.connection_id));
          setRefresh(value => value + 1);
        })}>{t("research.external.revoke")}</button>
      </div>
      {matching.length > 1 && <label className="research-field">{t("research.external.connection")}
        <select value={connection?.connection_id ?? ""} disabled={busy} onChange={event => changeSelection({ connectionId: event.target.value })}>
          {matching.map(row => <option key={row.connection_id}>{row.connection_id}</option>)}
        </select>
      </label>}
      {connection ? <>
        <p role="status">{t(connection.ready ? "research.external.ready" : "research.external.waiting")}</p>
        <label className="research-field">{t("research.external.file")}<input readOnly value={connection.connection_file} /></label>
        {connection.example_command && <label className="research-field">{t("research.external.command")}
          <textarea readOnly rows={3} value={connection.example_command} />
        </label>}
        <p>{t("research.external.smokeHelp")}</p>
      </> : <p>{t("research.external.noConnection")}</p>}
      <button type="button" className="research-primary" disabled={busy || runBusy || !prepared || !connection?.ready}
        onClick={() => prepared && connection && void perform(async signal => {
          const parsed = parseResearchObjectJson(parameters, t("ux.parameters"));
          const run = await manager.startExternalModel(prepared, connection, parsed, signal);
          signal.throwIfAborted();
          onRunCreated(run.run_id);
        })}>{t("research.external.checkAndRun")}</button>
    </>}
    {(error || bindingError) && <p role="alert">{error ?? bindingError}</p>}
  </section>;
}
