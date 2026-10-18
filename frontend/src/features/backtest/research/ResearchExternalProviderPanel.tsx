import { t } from "../../../i18n/index.js";
import { isExternalRevision } from "./externalProviderModel.js";
import type { BacktestResearchRuntime } from "./backtestResearchTypes.js";

export default function ResearchExternalProviderPanel({ runtime }: { runtime: BacktestResearchRuntime }) {
  const { capabilities, revisions, selectedRevisionId, datasets, selectedDatasetId, snapshot, busy,
    externalConnections, externalConnection } = runtime.view;
  const enabled = capabilities?.flags.BACKTEST_EXTERNAL_PROVIDER_ENABLED === true;
  const revision = revisions.find((item) => item.revision_id === selectedRevisionId);
  const external = isExternalRevision(revision);
  const copyCommand = async () => {
    if (!externalConnection?.example_command) return;
    try {
      await navigator.clipboard.writeText(externalConnection.example_command);
      runtime.actions.setNotice(t("research.external.commandCopied"));
    } catch { runtime.actions.setOperationError(t("research.external.copyFailed")); }
  };
  return (
    <section className="research-external-provider" aria-label={t("research.external.title")}>
      <h3>{t("research.external.title")}</h3>
      {!enabled ? <p className="research-empty">{t("research.external.disabled")}</p> : <>
        <p>{t("research.external.boundary")}</p>
        <button type="button" disabled={busy} onClick={() => void runtime.actions.registerExternalExample()}>{t("research.external.registerExample")}</button>
        {external && <>
          <dl className="research-facts">
            <div><dt>{t("research.external.model")}</dt><dd>{revision?.external_provider?.provider_id} · {revision?.external_provider?.provider_revision}</dd></div>
            <div><dt>{t("research.external.artifact")}</dt><dd><code>{revision?.external_provider?.artifact_sha256}</code></dd></div>
          </dl>
          <label className="research-field"><span>{t("research.external.dataset")}</span>
            <select value={selectedDatasetId} onChange={(event) => runtime.actions.selectDataset(event.target.value)}>
              {datasets.map((dataset) => <option key={dataset.dataset_id} value={dataset.dataset_id}>{dataset.name}</option>)}
            </select>
          </label>
          <p>{snapshot ? t("research.external.snapshot", { epoch: snapshot.data_epoch }) : t("research.external.selectInputs")}</p>
          <div className="research-button-row">
            <button type="button" disabled={busy || !snapshot} onClick={() => void runtime.actions.createExternalConnection()}>{t("research.external.create")}</button>
            <button type="button" disabled={busy || !externalConnection} onClick={() => void runtime.actions.revokeExternalConnection()}>{t("research.external.revoke")}</button>
          </div>
          {externalConnections.length > 1 && <label className="research-field"><span>{t("research.external.connection")}</span>
            <select value={externalConnection?.connection_id ?? ""} onChange={(event) => runtime.actions.selectExternalConnection(event.target.value)}>
              {externalConnections.map((connection) => <option key={connection.connection_id} value={connection.connection_id}>{connection.connection_id}</option>)}
            </select>
          </label>}
          {externalConnection ? <>
            <p role="status">{externalConnection.ready ? t("research.external.ready") : t("research.external.waiting")}</p>
            <label className="research-field"><span>{t("research.external.file")}</span><input readOnly value={externalConnection.connection_file} /></label>
            {externalConnection.example_command && <>
              <label className="research-field"><span>{t("research.external.command")}</span><textarea readOnly rows={3} value={externalConnection.example_command} /></label>
              <button type="button" onClick={() => void copyCommand()}>{t("research.external.copyCommand")}</button>
            </>}
            <p className="research-empty">{t("research.external.smokeHelp")}</p>
          </> : <p className="research-empty">{t("research.external.noConnection")}</p>}
        </>}
      </>}
    </section>
  );
}
