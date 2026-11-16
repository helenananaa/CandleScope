import { Button } from "../../components/ui/Button.js";
import { Badge, InlineAlert } from "../../components/ui/Display.js";
import { EmptyState } from "../../components/ui/EmptyState.js";
import { Checkbox, Field, Select, Textarea } from "../../components/ui/Field.js";
import { Icon } from "../../components/icons/Icon.js";
import { useEffect, useState } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import type { AiControlMode, AiControlStatus } from "./aiControlTypes.js";
import { workflowConnectionConfig } from "./workflowConnectionConfig.js";

/** Settings → AI MCP: lets a local AI client read or drive the open charts (desktop app only). */
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
  if (!bridge?.aiControlSetMode) {
    return <EmptyState icon={<Icon name="bot" size={22} />} title={t("aiControl.desktopOnly")} description={t("aiControl.description")} />;
  }
  const mode = status?.mode ?? "off";
  return <div className="st-ai">
    <section className="st-group">
      <div className="st-group-desc">{t("aiControl.description")} {t("aiControl.lifecycle")}</div>
      <div className="st-ai-status" role="status">
        <Badge tone={mode === "control" ? "warning" : mode === "read" ? "success" : "neutral"}>
          {t("aiControl.status", { mode: t(mode === "control" ? "aiControl.control" : mode === "read" ? "aiControl.read" : "aiControl.off") })}
        </Badge>
      </div>
      <InlineAlert>{t("aiControl.scope")}</InlineAlert>
      {status?.workflow && <Checkbox label={t("aiControl.workflows")} checked={workflows} disabled={busy}
        {...(workflows ? { description: t("aiControl.workflowScope") } : {})}
        onChange={(event) => { setWorkflows(event.target.checked); setGrant(false); }} />}
      <Checkbox label={t("aiControl.grant")} checked={grant} onChange={(event) => setGrant(event.target.checked)} />
      <div className="st-form-actions">
        <Button disabled={busy || !status} onClick={() => { void change("read"); }}>{t("aiControl.enableRead")}</Button>
        <Button disabled={busy || !status || !grant} onClick={() => { void change("control"); }}>{t("aiControl.enableControl")}</Button>
        <Button variant="ghost" disabled={busy || !status || status.mode === "off"} onClick={() => { void change("off"); }}>{t("aiControl.revoke")}</Button>
      </div>
      {error && <InlineAlert tone="danger">{error}</InlineAlert>}
    </section>

    {status?.endpoint && <section className="st-group">
      <div className="st-group-title">{t("aiControl.connectionTitle")}</div>
      <dl className="st-kv"><dt>{t("aiControl.endpoint")}</dt><dd><code>{status.endpoint}</code></dd></dl>
      <div className="st-form-actions">
        <Button onClick={() => { void copy(); }}>{t(copied ? "aiControl.copied" : "aiControl.copy")}</Button>
        <Button variant="ghost" aria-expanded={showConfiguration} onClick={() => setShowConfiguration((value) => !value)}>{t("aiControl.configuration")}</Button>
      </div>
      {showConfiguration && <Textarea className="st-code" readOnly rows={10} aria-label={t("aiControl.configuration")} value={connectionConfiguration} />}
      <div className="st-group-desc">{t("aiControl.secret")}</div>
    </section>}

    {status?.workflow?.enabled && <section className="st-group">
      <div className="st-group-title">{t("aiControl.workflowConfiguration")}</div>
      <div className="st-group-desc">{t("aiControl.workflowScope")}</div>
      <div className="st-form-actions">
        <Field label={t("aiControl.workflowFormat")}>
          <Select size="sm" value={format} onChange={(event) => { setFormat(event.target.value as "json" | "toml"); setWorkflowCopied(false); }}>
            <option value="json">JSON</option><option value="toml">TOML</option>
          </Select>
        </Field>
        <Button disabled={!workflowConfiguration || !status.workflow.adapterAvailable} onClick={() => { void copyWorkflow(); }}>{t(workflowCopied ? "aiControl.copied" : "aiControl.copy")}</Button>
      </div>
      <Textarea className="st-code" readOnly rows={10} aria-label={t("aiControl.workflowConfiguration")} value={workflowConfiguration} />
      {!status.workflow.adapterAvailable && <InlineAlert tone="danger">{t("aiControl.workflowAdapterMissing")}</InlineAlert>}
    </section>}

    <section className="st-group">
      <div className="st-group-title">{t("aiControl.views", { count: status?.views.length ?? 0 })}</div>
      {status?.views.length ? <ul className="st-plain-list">{status.views.map((view) => <li key={`${view.windowId}:${view.viewId}`}><code>{view.windowId} / {view.viewId}</code> · {view.kind}</li>)}</ul> : null}
    </section>
    <section className="st-group">
      <div className="st-group-title">{t("aiControl.audit")}</div>
      {!status?.audit.length ? <div className="st-group-desc">{t("aiControl.empty")}</div>
        : <ol className="st-plain-list">{status.audit.map((entry, index) => <li key={`${entry.at}:${index}`}><code>{entry.at} {entry.tool} {entry.windowId ?? ""} {entry.viewId ?? ""} {entry.outcome} {entry.elapsedMs} ms</code></li>)}</ol>}
    </section>
  </div>;
}
