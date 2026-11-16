import { useEffect, useState, useSyncExternalStore } from "react";
import { Badge, Button, Checkbox, Dialog, Field, FileDrop, InlineAlert, Select } from "../../components/ui/index.js";
import { notify } from "../../components/ui/overlay/overlayApi.js";
import { toastStore } from "../../components/ui/overlay/toastStore.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { extensionManagementRequest, pluginManagementAvailable, stageTrustedExtension } from "../plugins/pluginPlatformApi.js";
import type { ExtensionCatalog, ExtensionDiagnostics, ExtensionManifest } from "./contracts.js";
import { recoveryNotice } from "./recoveryNotice.js";
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

/** A caught failure as plain text, without the "Error:" prefix. Extension and host messages stay as written. */
function failureText(failure: unknown): string {
  return failure instanceof Error ? failure.message : String(failure);
}

/** Reload this window with frontend extensions skipped, or back to normal. */
function reloadExtensions(off: boolean): void {
  const url = new URL(location.href);
  if (off) url.searchParams.set("extensions", "off"); else url.searchParams.delete("extensions");
  location.assign(url.href);
}

/** Recovery actions that work even when an extension has broken the page. */
function RecoveryActions() {
  return extensionSafeMode()
    ? <Button size="sm" variant="ghost" onClick={() => reloadExtensions(false)}>{t("extensions.reloadWith")}</Button>
    : <Button size="sm" variant="ghost" onClick={() => reloadExtensions(true)}>{t("extensions.reloadWithout")}</Button>;
}

export default function ExtensionManager() {
  useLocale();
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
    void readSnapshot().then((value) => { if (current) { setCatalog(value.catalog); setDesktop(value.desktop); } }).catch((failure) => { if (current) setError(failureText(failure)); });
    return () => { current = false; };
  }, [available]);
  async function run(action: () => Promise<void>) {
    setBusy(true); setError("");
    try { await action(); await reload(); } catch (failure) { setError(failureText(failure)); }
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
  const realmLabels = { frontend: t("extensions.realm.frontend"), backend: t("extensions.realm.backend"), desktop: t("extensions.realm.desktop") };
  const statuses = {
    "safe-mode": t("extensions.status.safeMode"),
    "unavailable": t("extensions.status.unavailable"),
    "pending-stop": t("extensions.status.pendingStop"),
    "pending-restart": t("extensions.status.pendingRestart"),
    "failed": t("extensions.status.failed"),
    "running": t("extensions.status.running"),
    "pending-start": t("extensions.status.pendingStart"),
    "stopped": t("extensions.status.stopped"),
  };
  const locked = busy || !available;
  const runtimeErrors = [
    error || state.errors.runtime ? { realm: null, message: error || state.errors.runtime } : null,
    catalog?.backendErrors?.runtime ? { realm: realmLabels.backend, message: catalog.backendErrors.runtime } : null,
    desktop?.errors.runtime ? { realm: realmLabels.desktop, message: desktop.errors.runtime } : null,
  ].filter((item): item is { realm: string | null; message: string } => item !== null);
  return <section className="extension-manager" aria-busy={busy}>
    <header className="extension-manager-head">
      <div>
        <h3>{t("extensions.title")}</h3>
        <p>{t("extensions.description")}</p>
      </div>
      {/* Outside the locked fieldset: leaving or entering recovery must work even when management cannot. */}
      {!extensionSafeMode() && <RecoveryActions />}
    </header>
    {(extensionSafeMode() || catalog?.safeMode || state.safeMode) && <InlineAlert tone="warning" action={extensionSafeMode() ? <RecoveryActions /> : undefined}>
      {t("extensions.safeMode")}
    </InlineAlert>}
    {!available && <InlineAlert>{t("extensions.desktopOnly")}</InlineAlert>}
    {runtimeErrors.map((item) => <InlineAlert key={item.realm ?? "window"} tone="danger" title={item.realm ? t("extensions.realmError", { realm: item.realm }) : t("extensions.runtimeError")}>
      <code className="extension-detail">{item.message}</code>
    </InlineAlert>)}
    {catalog && [...catalog.backendActive ?? [], ...desktop?.active ?? []].some((entry) => !catalog.plugins.some((item) => item.manifest.id === entry.id)) && <InlineAlert>{t("extensions.orphanRunning")}</InlineAlert>}
    {state.reloadRequired && <InlineAlert action={<Button size="sm" onClick={() => location.reload()}>{t("extensions.reload")}</Button>}>
      {t("extensions.reloadRequired")}
    </InlineAlert>}
    <fieldset className="extension-manager-body" disabled={locked}>
      <div className="extension-toolbar">
        <FileDrop compact label={t("extensions.import")} accept=".csext" disabled={locked}
          onFiles={([file]) => { if (file) void run(async () => { setReview(null); setAccepted(false); setReview(await stageTrustedExtension(file) as Review); }); }} />
        <div className="extension-actions">
          <Button size="sm" onClick={() => void run(async () => { await change("disable-all", ""); })}>{t("extensions.disableAll")}</Button>
          <Button size="sm" variant="ghost" onClick={() => void run(reload)}>{t("extensions.refresh")}</Button>
        </div>
      </div>
      {review && <div className="extension-review" role="region" aria-label={t("extensions.approval")}>
        <strong>{review.manifest.name} · {review.manifest.version}</strong>
        <p>{review.manifest.description}</p>
        <InlineAlert tone={review.manifest.trust === "full-trust" ? "warning" : "info"}>
          {review.manifest.trust === "full-trust"
            ? t("extensions.fullTrust")
            : t("extensions.themeOnly")}
        </InlineAlert>
        <dl className="extension-facts">
          <div><dt>{t("extensions.realms")}</dt><dd>{Object.keys(review.manifest.entries ?? {}).map((realm) => realm in realmLabels ? realmLabels[realm as keyof typeof realmLabels] : realm).join(" · ") || t("extensions.none")}</dd></div>
          <div><dt>{t("extensions.source")}</dt><dd>{t("extensions.localImport")}</dd></div>
          <div><dt>SHA-256</dt><dd><code className="extension-detail">{review.digest}</code></dd></div>
        </dl>
        <Checkbox checked={accepted} onChange={(event) => setAccepted(event.target.checked)} label={t("extensions.accept")} />
        <div className="extension-actions">
          <Button size="sm" variant="primary" disabled={!accepted} onClick={() => void run(async () => {
            await extensionManagementRequest("/change", { action: "activate", id: review.manifest.id, digest: review.digest, acknowledgement: `${review.manifest.trust}:${review.digest}` });
            setReview(null); setAccepted(false); await refreshExtensions(true);
          })}>{t("extensions.confirm")}</Button>
          <Button size="sm" variant="ghost" onClick={() => setReview(null)}>{t("common.cancel")}</Button>
        </div>
      </div>}
      <div className="extension-choices">
        <Field label={t("extensions.theme")}>
          <Select size="sm" value={catalog?.theme ?? ""} onChange={(event) => void run(() => change("theme", event.target.value))}>
            <option value="">{t("extensions.appDefault")}</option>
            {catalog?.plugins.filter((item) => item.enabled && !item.error && item.manifest.theme).map((item) => <option key={item.manifest.id} value={item.manifest.id}>{item.manifest.name}</option>)}
          </Select>
        </Field>
        <Field label={t("extensions.layout")}>
          <Select size="sm" value={catalog?.layout ?? ""} onChange={(event) => void run(() => change("layout", event.target.value))}>
            <option value="">{t("extensions.appDefault")}</option>
            {catalog?.plugins.filter((item) => item.enabled && !item.error && item.manifest.layout).map((item) => <option key={item.manifest.id} value={item.manifest.id}>{item.manifest.name}</option>)}
          </Select>
        </Field>
      </div>
      {catalog?.plugins.map((item) => <article className="extension-item" key={item.manifest.id}>
        <header>
          <strong>{item.manifest.name} · {item.manifest.version}</strong>
          <Badge tone={item.enabled ? "success" : "neutral"}>{item.enabled ? t("extensions.enabled") : t("extensions.disabled")}</Badge>
        </header>
        {Object.keys(item.manifest.entries ?? {}).some((key) => key !== "frontend") && <p className="extension-note">{t("extensions.restartNote")}</p>}
        {item.error && <InlineAlert tone="danger"><code className="extension-detail">{item.error}</code></InlineAlert>}
        <dl className="extension-realms">
          {realms.filter((realm) => item.manifest.entries?.[realm] || actual[realm]?.some((entry) => entry.id === item.manifest.id)).map((realm) => {
            const running = actual[realm]?.find((entry) => entry.id === item.manifest.id);
            const failure = realmErrors[realm]?.[item.manifest.id];
            const safe = realm === "frontend" ? extensionSafeMode() || Boolean(catalog.safeMode) : realm === "desktop" ? Boolean(desktop?.safeMode) : Boolean(catalog.safeMode);
            const status = extensionRuntimeStatus(item, realm, actual[realm], failure, safe);
            return <div key={realm} data-extension-runtime={realm} data-runtime-status={status}>
              <dt>{realmLabels[realm]}</dt>
              <dd>{statuses[status]}{running ? ` · ${running.version}` : ""}</dd>
              {failure && <dd className="extension-failure" role="alert"><code className="extension-detail">{failure}</code></dd>}
            </div>;
          })}
        </dl>
        <div className="extension-actions">
          <Button size="sm" onClick={() => void run(() => item.enabled ? change("disable", item.manifest.id) : openReview(item.digest))}>{item.enabled ? t("extensions.disable") : t("extensions.enable")}</Button>
          <Button size="sm" variant="ghost" className="extension-uninstall" onClick={() => void run(() => change("uninstall", item.manifest.id))}>{t("extensions.uninstall")}</Button>
          {item.history.filter((digest) => digest !== item.digest).map((digest) => <Button size="sm" variant="ghost" key={digest} onClick={() => void run(() => openReview(digest))}>{t("extensions.reviewPrevious")} {digest.slice(0, 8)}</Button>)}
        </div>
      </article>)}
    </fieldset>
  </section>;
}

/**
 * Says so when an extension failed to load or extensions are off, and opens management in a dialog.
 * Rendered outside extension-replaceable slots, so it works when an extension breaks the page.
 * Day to day, extensions are managed in Settings → 插件与扩展 → 可信扩展.
 */
export function ExtensionRecovery() {
  useLocale();
  const [open, setOpen] = useState(false);
  const state = useSyncExternalStore(subscribeExtensions, getExtensionState, getExtensionState);
  const notice = recoveryNotice(state, extensionSafeMode());
  const manageLabel = t("extensions.manage");
  const { tone, title, message } = notice ?? {};
  // One notice per situation; a newly failed extension shows it again after a dismissal.
  useEffect(() => {
    if (!tone || !title) return undefined;
    const id = notify({ tone, title, ...(message ? { message } : {}), action: { label: manageLabel, onClick: () => setOpen(true) }, durationMs: 0 });
    return () => toastStore.dismiss(id);
  }, [tone, title, message, manageLabel]);
  return <Dialog open={open} onClose={() => setOpen(false)} size="lg" title={t("extensions.recoveryTitle")}>
    <ExtensionManager />
  </Dialog>;
}
