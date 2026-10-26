import { useEffect, useState } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import type { AiControlMode, AiControlStatus } from "./aiControlTypes.js";
import { workflowConnectionConfig } from "./workflowConnectionConfig.js";

export default function AiControlSettingsPanel() {
  useLocale();
  const bridge = globalThis.window?.candlescopeDesktop;
  const [status, setStatus] = useState<AiControlStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [grant, setGrant] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [showConfiguration, setShowConfiguration] = useState(false);
  const [workflows, setWorkflows] = useState(false);
  const [format, setFormat] = useState<"json" | "toml">("json");
  const [workflowCopied, setWorkflowCopied] = useState(false);
  useEffect(() => {
    if (!bridge?.aiControlStatus) return;
    let alive = true;
    const refresh = () => { void bridge.aiControlStatus!().then((value) => { if (alive) setStatus(value); })
      .catch(() => { if (alive) setError(t("aiControl.failed")); }); };
    refresh(); const timer = setInterval(refresh, 2000);
    return () => { alive = false; clearInterval(timer); };
  }, [bridge]);
  async function change(mode: AiControlMode) {
    if (!bridge?.aiControlSetMode) return;
    setBusy(true); setError(null); setCopied(false); setShowConfiguration(false);
    try { setStatus(await bridge.aiControlSetMode(mode, mode !== "off" && workflows)); setGrant(false); setWorkflowCopied(false); }
    catch { setError(t("aiControl.failed")); }
    finally { setBusy(false); }
  }
  const connectionConfiguration = status?.endpoint && status.token ? JSON.stringify({ mcpServers: { candlescope: {
    type: "http", url: status.endpoint, headers: { Authorization: `Bearer ${status.token}` },
  } } }, null, 2) : "";
  const workflowConfiguration = workflowConnectionConfig(status?.workflow, format);
  async function copyWorkflow() {
    try { await navigator.clipboard.writeText(workflowConfiguration); setWorkflowCopied(true); setError(null); }
    catch { setError(t("aiControl.copyFailed")); }
  }
  async function copy() {
    if (!status?.endpoint || !status.token) return;
    try {
      await navigator.clipboard.writeText(connectionConfiguration); setCopied(true); setError(null);
    } catch { setError(t("aiControl.copyFailed")); }
  }
  if (!bridge?.aiControlSetMode) return <div className="st-info-box">{t("aiControl.desktopOnly")}</div>;
  return <section className="st-section">
    <h3>{t("settings.category.ai")}</h3>
    <p>{t("aiControl.description")}</p><p>{t("aiControl.lifecycle")}</p>
    <p role="status">{t("aiControl.status", { mode: t(status?.mode === "control" ? "aiControl.control" : status?.mode === "read" ? "aiControl.read" : "aiControl.off") })}</p>
    <div className="st-info-box">{t("aiControl.scope")}</div>
    {status?.workflow && <p><label><input type="checkbox" checked={workflows} disabled={busy}
      onChange={(event) => { setWorkflows(event.target.checked); setGrant(false); }} /> {t("aiControl.workflows")}</label></p>}
    {workflows && <p>{t("aiControl.workflowScope")}</p>}
    <p><label><input type="checkbox" checked={grant} onChange={(event) => setGrant(event.target.checked)} /> {t("aiControl.grant")}</label></p>
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
      <button className="st-btn" disabled={busy || !status} onClick={() => { void change("read"); }}>{t("aiControl.enableRead")}</button>
      <button className="st-btn" disabled={busy || !status || !grant} onClick={() => { void change("control"); }}>{t("aiControl.enableControl")}</button>
      <button className="st-btn" disabled={busy || !status || status.mode === "off"} onClick={() => { void change("off"); }}>{t("aiControl.revoke")}</button>
    </div>
    {status?.endpoint && <><p><code>{status.endpoint}</code></p>
      <button className="st-btn" onClick={() => { void copy(); }}>{t(copied ? "aiControl.copied" : "aiControl.copy")}</button>
      <button className="st-btn" aria-expanded={showConfiguration} onClick={() => setShowConfiguration((value) => !value)}>{t("aiControl.configuration")}</button>
      {showConfiguration && <textarea readOnly rows={10} aria-label={t("aiControl.configuration")} value={connectionConfiguration} style={{ width: "100%", fontFamily: "monospace" }} />}
      <p>{t("aiControl.secret")}</p></>}
    {status?.workflow?.enabled && <div className="st-info-box">
      <h4>{t("aiControl.workflowConfiguration")}</h4>
      <p>{t("aiControl.workflowScope")}</p>
      <label>{t("aiControl.workflowFormat")} <select value={format} onChange={(event) => { setFormat(event.target.value as "json" | "toml"); setWorkflowCopied(false); }}><option value="json">JSON</option><option value="toml">TOML</option></select></label>
      <p><button className="st-btn" disabled={!workflowConfiguration || !status.workflow.adapterAvailable} onClick={() => { void copyWorkflow(); }}>{t(workflowCopied ? "aiControl.copied" : "aiControl.copy")}</button></p>
      <textarea readOnly rows={10} aria-label={t("aiControl.workflowConfiguration")} value={workflowConfiguration} style={{ width: "100%", fontFamily: "monospace" }} />
      {!status.workflow.adapterAvailable && <p role="alert">{t("aiControl.workflowAdapterMissing")}</p>}
    </div>}
    {error && <p role="alert">{error}</p>}
    <h4>{t("aiControl.views", { count: status?.views.length ?? 0 })}</h4>
    <ul>{status?.views.map((view) => <li key={`${view.windowId}:${view.viewId}`}><code>{view.windowId} / {view.viewId}</code> · {view.kind}</li>)}</ul>
    <h4>{t("aiControl.audit")}</h4>{!status?.audit.length && <p>{t("aiControl.empty")}</p>}
    <ol>{status?.audit.map((entry, index) => <li key={`${entry.at}:${index}`}><code>{entry.at} {entry.tool} {entry.windowId ?? ""} {entry.viewId ?? ""} {entry.outcome} {entry.elapsedMs} ms</code></li>)}</ol>
  </section>;
}
