import { useEffect, useState, useSyncExternalStore } from "react";
import { Button, Dialog, InlineAlert } from "../../components/ui/index.js";
import { notify } from "../../components/ui/overlay/overlayApi.js";
import { toastStore } from "../../components/ui/overlay/toastStore.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { pluginManagementAvailable } from "../plugins/pluginPlatformApi.js";
import { recoveryNotice } from "./recoveryNotice.js";
import { extensionSafeMode, getExtensionState, subscribeExtensions } from "./state.js";
import UnifiedPluginManager from "./UnifiedPluginManager.js";
import { getUnifiedState, subscribeUnified } from "./unifiedRuntime.js";

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
  const state = useSyncExternalStore(subscribeExtensions, getExtensionState, getExtensionState);
  const safe = extensionSafeMode();
  return <section className="extension-manager">
    <header className="extension-manager-head"><h3>{t("extensions.title")}</h3>
      {!safe && <RecoveryActions />}
    </header>
    {(safe || state.safeMode) && <InlineAlert tone="warning" action={safe ? <RecoveryActions /> : undefined}>
      {t("extensions.safeMode")}
    </InlineAlert>}
    {!pluginManagementAvailable() && <InlineAlert>{t("extensions.desktopOnly")}</InlineAlert>}
    <UnifiedPluginManager showAppearance />
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
  const unified = useSyncExternalStore(subscribeUnified, getUnifiedState, getUnifiedState);
  const notice = recoveryNotice({ ...state, errors: { ...state.errors, ...unified.errors } }, extensionSafeMode());
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
