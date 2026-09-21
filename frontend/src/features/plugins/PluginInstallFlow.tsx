import { useEffect, useState } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { LocalTrustInstallPanel } from "./PluginManagementSections.js";
import type { PluginPlatformRuntime } from "./pluginPlatformTypes.js";

export default function PluginInstallFlow({ runtime, onDone, onPendingChange }: { runtime: PluginPlatformRuntime; onDone(): void; onPendingChange?(pending: boolean): void }) {
  useLocale();
  const [pending, setPending] = useState(false);
  const [installed, setInstalled] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { onPendingChange?.(pending); }, [pending, onPendingChange]);
  useEffect(() => () => onPendingChange?.(false), [onPendingChange]);
  return <section className="pc-install-flow">
    <header><h3>{t("pc.install")}</h3><p>{t(runtime.view.catalog?.trustUx?.enabled ? "plugin.trust.localHint" : "plugin.localInstallHint")}</p></header>
    {runtime.view.catalog?.trustUx?.enabled ? <LocalTrustInstallPanel runtime={runtime} onPendingChange={setPending} /> : <section className="plugin-settings-card">
      <h4>{t("plugin.localInstall")}</h4>
      <p>{t("plugin.hashHint")}</p>
      <input type="file" accept=".cspkg,application/vnd.candlescope.plugin+zip" aria-label={t("plugin.pickCspkg")} data-plugin-install-input disabled={pending || !runtime.view.managementAvailable}
        onChange={async (event) => {
          const file = event.target.files?.[0]; event.target.value = "";
          if (!file || pending) return;
          setPending(true); setError(null); setInstalled(false);
          try { await runtime.actions.installBundle(file); setInstalled(true); }
          catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
          finally { setPending(false); }
        }} />
      {pending && <p role="status">{t("pc.working")}</p>}
      {error && <p role="alert">{error}</p>}
      {installed && <p role="status">{t("plugin.installedHint")}</p>}
    </section>}
    <button type="button" disabled={pending} onClick={onDone}>{t("pc.installed")}</button>
  </section>;
}
