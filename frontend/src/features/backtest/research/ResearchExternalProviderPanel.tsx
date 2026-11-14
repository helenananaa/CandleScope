import { Button, Field, Input, Select, Textarea } from "../../../components/ui/index.js";
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
      <h4>{t("research.external.title")}</h4>
      {!enabled ? <p className="research-empty">{t("research.external.disabled")}</p> : <>
        <p className="research-panel-copy">{t("research.external.boundary")}</p>
        <Button size="sm" disabled={busy} onClick={() => void runtime.actions.registerExternalExample()}>{t("research.external.registerExample")}</Button>
        {external && <>
          <dl className="research-facts">
            <div><dt>{t("research.external.model")}</dt><dd>{revision?.external_provider?.provider_id} · {revision?.external_provider?.provider_revision}</dd></div>
            <div><dt>{t("research.external.artifact")}</dt><dd><code>{revision?.external_provider?.artifact_sha256}</code></dd></div>
          </dl>
          <Field label={t("research.external.dataset")}>
            <Select size="sm" value={selectedDatasetId} onChange={(event) => runtime.actions.selectDataset(event.target.value)}>
              {datasets.map((dataset) => <option key={dataset.dataset_id} value={dataset.dataset_id}>{dataset.name}</option>)}
            </Select>
          </Field>
          <p className="research-panel-copy">{snapshot ? t("research.external.snapshot", { epoch: snapshot.data_epoch }) : t("research.external.selectInputs")}</p>
          <div className="research-button-row">
            <Button size="sm" variant="primary" disabled={busy || !snapshot} onClick={() => void runtime.actions.createExternalConnection()}>{t("research.external.create")}</Button>
            <Button size="sm" variant="danger" disabled={busy || !externalConnection} onClick={() => void runtime.actions.revokeExternalConnection()}>{t("research.external.revoke")}</Button>
          </div>
          {externalConnections.length > 1 && <Field label={t("research.external.connection")}>
            <Select size="sm" value={externalConnection?.connection_id ?? ""} onChange={(event) => runtime.actions.selectExternalConnection(event.target.value)}>
              {externalConnections.map((connection) => <option key={connection.connection_id} value={connection.connection_id}>{connection.connection_id}</option>)}
            </Select>
          </Field>}
          {externalConnection ? <>
            <p className="research-panel-copy" role="status">{externalConnection.ready ? t("research.external.ready") : t("research.external.waiting")}</p>
            <Field label={t("research.external.file")}><Input size="sm" readOnly value={externalConnection.connection_file} /></Field>
            {externalConnection.example_command && <>
              <Field label={t("research.external.command")}><Textarea className="research-json-editor" readOnly rows={3} value={externalConnection.example_command} /></Field>
              <Button size="sm" variant="ghost" onClick={() => void copyCommand()}>{t("research.external.copyCommand")}</Button>
            </>}
            <p className="research-empty">{t("research.external.smokeHelp")}</p>
          </> : <p className="research-empty">{t("research.external.noConnection")}</p>}
        </>}
      </>}
    </section>
  );
}
