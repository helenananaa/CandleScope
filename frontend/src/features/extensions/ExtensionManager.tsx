import { useEffect, useState, useSyncExternalStore } from "react";
import { useExtensionText } from "./hooks.js";
import { extensionManagementRequest, pluginManagementAvailable, stageTrustedExtension } from "../plugins/pluginPlatformApi.js";
import type { ExtensionCatalog, ExtensionDiagnostics, ExtensionManifest } from "./contracts.js";
import { extensionRuntimeStatus } from "./runtimeStatus.js";
import { refreshExtensions } from "./runtime.js";
import { extensionSafeMode, getExtensionState, subscribeExtensions } from "./state.js";

interface Review { digest: string; manifest: ExtensionManifest; signed: false }
const realms = ["frontend", "backend", "desktop"] as const;
async function readSnapshot() {
  const [catalog, desktop] = await Promise.all([
    extensionManagementRequest("") as Promise<ExtensionCatalog>,
    window.candlescopeDesktop?.getExtensionDiagnostics?.(),
  ]);
  return { catalog, desktop: desktop ?? null };
}

export default function ExtensionManager() {
  const text = useExtensionText();
  const [catalog, setCatalog] = useState<ExtensionCatalog | null>(null);
  const [desktop, setDesktop] = useState<ExtensionDiagnostics | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const state = useSyncExternalStore(subscribeExtensions, getExtensionState, getExtensionState);
  const available = pluginManagementAvailable();
  async function reload() { const value = await readSnapshot(); setCatalog(value.catalog); setDesktop(value.desktop); }
  useEffect(() => {
    if (!available) return;
    let current = true;
    void readSnapshot().then((value) => { if (current) { setCatalog(value.catalog); setDesktop(value.desktop); } }).catch((failure) => { if (current) setError(String(failure)); });
    return () => { current = false; };
  }, [available]);
  async function run(action: () => Promise<void>) {
    setBusy(true); setError("");
    try { await action(); await reload(); } catch (failure) { setError(String(failure)); }
    finally { setBusy(false); }
  }
  async function change(action: string, id: string) {
    await extensionManagementRequest("/change", { action, id });
    await refreshExtensions(true);
  }
  async function openReview(digest: string) {
    const value = await extensionManagementRequest(`/review/${digest}`) as Review;
    setAccepted(false); setReview(value);
  }
  const actual = { frontend: state.running, backend: catalog?.backendActive, desktop: desktop?.active };
  const realmErrors = { frontend: state.errors, backend: catalog?.backendErrors, desktop: desktop?.errors };
  const realmLabels = { frontend: text("当前窗口", "This window"), backend: text("后端", "Backend"), desktop: text("桌面", "Desktop") };
  const statuses = {
    "safe-mode": text("恢复模式，未加载", "Skipped in recovery mode"),
    "unavailable": text("运行状态不可用", "Runtime status unavailable"),
    "pending-stop": text("仍在运行，重启后停用", "Still running; restart to stop"),
    "pending-restart": text("运行旧版本，重启后切换", "Previous activation running; restart to apply"),
    "failed": text("加载失败", "Failed to load"),
    "running": text("运行中", "Running"),
    "pending-start": text("等待加载或重启", "Awaiting load or restart"),
    "stopped": text("未运行", "Stopped"),
  };
  return <section className="extension-manager">
    <h3>{text("可信扩展", "Trusted extensions")}</h3>
    <p>{text("安装主题、布局和完整功能扩展。代码扩展可以访问宿主与当前用户的本地资源。", "Install themes, layouts and host extensions. Code extensions can access the host and local resources available to your user.")}</p>
    {(extensionSafeMode() || catalog?.safeMode) && <p role="status">{text("恢复模式：扩展暂不运行，可以停用或回退版本。", "Recovery mode: extensions are not running. Disable or roll back a version here.")}</p>}
    {!available && <p>{text("请在桌面版中管理扩展。", "Manage extensions in the desktop app.")}</p>}
    <fieldset disabled={busy || !available}>
      <div className="extension-actions">
        <label>{text("导入扩展包", "Import extension package")}<input type="file" accept=".csext" onChange={(event) => {
          const file = event.target.files?.[0]; event.target.value = "";
          if (file) void run(async () => { setReview(null); setAccepted(false); setReview(await stageTrustedExtension(file) as Review); });
        }} /></label>
        <button type="button" onClick={() => void run(async () => { await change("disable-all", ""); })}>{text("停用全部扩展", "Disable all extensions")}</button>
        <button type="button" onClick={() => void run(reload)}>{text("刷新", "Refresh")}</button>
      </div>
      {review && <div className="extension-review" role="region" aria-label={text("扩展授权", "Extension approval")}>
        <strong>{review.manifest.name} · {review.manifest.version}</strong>
        <p>{review.manifest.description}</p>
        <p>{review.manifest.trust === "full-trust"
          ? text("完全可信：允许此版本的代码进入应用。它可以更改界面、访问数据，以及执行声明的后端或桌面代码。", "Full trust: allow this version to execute inside the app, change the UI, access data, and run its declared backend or desktop code.")
          : text("此包只提供主题数据，不执行扩展代码。", "This package provides theme data without executing extension code.")}</p>
        <p>{text("执行位置：", "Execution realms: ")}{Object.keys(review.manifest.entries ?? {}).join(", ") || text("无", "None")}</p>
        <p>{text("本地导入，发布者签名未验证。", "Local import; publisher signature is not verified.")}</p>
        <code>{review.digest}</code>
        <label><input type="checkbox" checked={accepted} onChange={(event) => setAccepted(event.target.checked)} />{text("我信任并启用这个版本", "I trust and enable this version")}</label>
        <div className="extension-actions">
          <button type="button" disabled={!accepted} onClick={() => void run(async () => {
            await extensionManagementRequest("/change", { action: "activate", id: review.manifest.id, digest: review.digest, acknowledgement: `${review.manifest.trust}:${review.digest}` });
            setReview(null); setAccepted(false); await refreshExtensions(true);
          })}>{text("确认启用", "Enable this version")}</button>
          <button type="button" onClick={() => setReview(null)}>{text("取消", "Cancel")}</button>
        </div>
      </div>}
      <div className="extension-actions">
        <label>{text("主题", "Theme")}<select value={catalog?.theme ?? ""} onChange={(event) => void run(() => change("theme", event.target.value))}>
          <option value="">{text("应用默认", "App default")}</option>
          {catalog?.plugins.filter((item) => item.enabled && !item.error && item.manifest.theme).map((item) => <option key={item.manifest.id} value={item.manifest.id}>{item.manifest.name}</option>)}
        </select></label>
        <label>{text("布局", "Layout")}<select value={catalog?.layout ?? ""} onChange={(event) => void run(() => change("layout", event.target.value))}>
          <option value="">{text("应用默认", "App default")}</option>
          {catalog?.plugins.filter((item) => item.enabled && !item.error && item.manifest.layout).map((item) => <option key={item.manifest.id} value={item.manifest.id}>{item.manifest.name}</option>)}
        </select></label>
      </div>
      {catalog?.plugins.map((item) => <article className="extension-item" key={item.manifest.id}>
        <strong>{item.manifest.name} · {item.manifest.version}</strong>
        <span>{item.enabled ? text("已启用", "Enabled") : text("已停用", "Disabled")}</span>
        {Object.keys(item.manifest.entries ?? {}).some((key) => key !== "frontend") && <p>{text("后端和桌面入口的启用、停用及升级需重启应用生效。", "Restart the app to apply backend and desktop entry changes.")}</p>}
        {item.error && <p role="alert">{item.error}</p>}
        {realms.filter((realm) => item.manifest.entries?.[realm] || actual[realm]?.some((entry) => entry.id === item.manifest.id)).map((realm) => {
          const running = actual[realm]?.find((entry) => entry.id === item.manifest.id);
          const failure = realmErrors[realm]?.[item.manifest.id];
          const safe = realm === "frontend" ? extensionSafeMode() || Boolean(catalog.safeMode) : realm === "desktop" ? Boolean(desktop?.safeMode) : Boolean(catalog.safeMode);
          const status = extensionRuntimeStatus(item, realm, actual[realm], failure, safe);
          return <div key={realm} data-extension-runtime={realm} data-runtime-status={status}>
            <p>{realmLabels[realm]}：{statuses[status]}{running ? ` · ${running.version}` : ""}</p>
            {failure && <p role="alert">{realmLabels[realm]}：{failure}</p>}
          </div>;
        })}
        <div className="extension-actions">
          <button type="button" onClick={() => void run(() => item.enabled ? change("disable", item.manifest.id) : openReview(item.digest))}>{item.enabled ? text("停用", "Disable") : text("启用", "Enable")}</button>
          <button type="button" onClick={() => void run(() => change("uninstall", item.manifest.id))}>{text("卸载", "Uninstall")}</button>
          {item.history.filter((digest) => digest !== item.digest).map((digest) => <button key={digest} type="button" onClick={() => void run(() => openReview(digest))}>{text("查看旧版本", "Review previous version")} {digest.slice(0, 8)}</button>)}
        </div>
      </article>)}
    </fieldset>
    {(error || state.errors.runtime) && <p role="alert">{error || state.errors.runtime}</p>}
    {catalog?.backendErrors?.runtime && <p role="alert">{realmLabels.backend}：{catalog.backendErrors.runtime}</p>}
    {desktop?.errors.runtime && <p role="alert">{realmLabels.desktop}：{desktop.errors.runtime}</p>}
    {catalog && [...catalog.backendActive ?? [], ...desktop?.active ?? []].some((entry) => !catalog.plugins.some((item) => item.manifest.id === entry.id)) && <p role="status">{text("已卸载扩展的后台代码仍在运行，请重启应用完成卸载。", "An uninstalled extension still has background code running. Restart the app to finish removal.")}</p>}
    {state.reloadRequired && <p role="status">{text("代码扩展已变更，重新加载窗口以清除全部运行状态。", "Code extensions changed. Reload the window to clear all runtime state.")} <button type="button" onClick={() => location.reload()}>{text("重新加载", "Reload")}</button></p>}
  </section>;
}

/** Rendered outside extension-replaceable slots, also available before an extension loads. */
export function ExtensionRecovery() {
  const text = useExtensionText();
  const [open, setOpen] = useState(extensionSafeMode());
  const state = useSyncExternalStore(subscribeExtensions, getExtensionState, getExtensionState);
  return <aside className="extension-recovery">
    <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}>{text("扩展恢复", "Extension recovery")}{Object.keys(state.errors).length ? " !" : ""}</button>
    {open && <div className="extension-recovery-panel">
      <button type="button" onClick={() => { const url = new URL(location.href); url.searchParams.set("extensions", "off"); location.assign(url.href); }}>{text("不加载扩展并刷新", "Reload without extensions")}</button>
      <ExtensionManager />
    </div>}
  </aside>;
}
