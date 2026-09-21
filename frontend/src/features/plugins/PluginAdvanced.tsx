import { useEffect, useState } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { RuntimeRegistryPanel } from "./PluginManagementSections.js";
import type { PluginPlatformRuntime, PluginV1CompatibilityPreview } from "./pluginPlatformTypes.js";
export default function PluginAdvanced({ runtime }: { runtime: PluginPlatformRuntime }) {
  useLocale();
  const [compatibilityPreview, setCompatibilityPreview] = useState<PluginV1CompatibilityPreview | null>(null);
  const [compatibilityBusy, setCompatibilityBusy] = useState<"import" | "rollback" | null>(null);
  const compatibility = runtime.view.catalog?.compatibility ?? null;
  const platformEnabled = runtime.view.catalog?.platform.enabled === true;
  const availableRuntimeCount = compatibility?.contributions.filter((item) => item.available).length ?? 0;
  useEffect(() => { setCompatibilityPreview(null); }, [compatibility?.import.sourceSha256]);
  const previewCompatibility = async (action: "import" | "rollback") => {
    setCompatibilityBusy(action);
    try {
      setCompatibilityPreview(
        action === "import"
          ? await runtime.actions.previewV1CompatibilityImport()
          : await runtime.actions.previewV1CompatibilityRollback(),
      );
    } catch {
      setCompatibilityPreview(null);
    } finally {
      setCompatibilityBusy(null);
    }
  };
  const applyCompatibility = async () => {
    if (!compatibilityPreview?.available || !compatibilityPreview.previewSha256) return;
    const action = compatibilityPreview.action;
    if (!window.confirm(
      action === "import"
        ? t("plugin.host.v1ImportConfirm")
        : t("plugin.host.v1RollbackConfirm"),
    )) return;
    setCompatibilityBusy(action);
    try {
      if (action === "import") {
        await runtime.actions.applyV1CompatibilityImport(compatibilityPreview.previewSha256);
      } else {
        await runtime.actions.applyV1CompatibilityRollback(compatibilityPreview.previewSha256);
      }
      setCompatibilityPreview(null);
    } catch {
      // Runtime publishes the fail-closed Host response.
    } finally {
      setCompatibilityBusy(null);
    }
  };
  return <div className="pc-advanced">
    <section className="plugin-settings-card">
      <h3>{t("plugin.marketplace")}</h3>
      <p>{t("plugin.market.policyHint")}</p>
      {runtime.view.marketplaceCatalog?.marketplaces.length ? runtime.view.marketplaceCatalog.marketplaces.map((source) => <article key={source.marketplaceId}>
        <strong>{source.marketplaceId}</strong><p>{source.indexUrl}</p><p>{source.keyId}</p>
        <p>{source.cache.status === "valid" ? t("plugin.market.cacheVerified", { sequence: source.cache.sequence, expires: source.cache.expiresAt }) : t("plugin.market.cacheUnavailable", { reason: source.cache.reason ?? t("plugin.market.noVerifiedIndex") })}</p>
      </article>) : <p>{t("plugin.market.missing")}</p>}
    </section>
    {platformEnabled && runtime.view.catalog?.runtimeRegistry && <RuntimeRegistryPanel status={runtime.view.catalog.runtimeRegistry} />}
      {compatibility && (
        <section className="plugin-settings-card plugin-v1-compatibility" data-v1-compatibility-status={compatibility.import.status}>
          <header className="plugin-settings-card-header">
            <div>
              <h3>{t("plugin.scriptRuntimes")}</h3>
              <p>{t("plugin.runtimeDesc")}</p>
            </div>
            <span className={`plugin-state-pill ${availableRuntimeCount > 0 ? "is-ready" : "is-muted"}`}>{t("plugin.availableCount", { count: availableRuntimeCount })}</span>
          </header>
          <div className="plugin-runtime-list">
            {compatibility.contributions.map((contribution) => (
              <article key={contribution.id} data-v1-runtime={contribution.runtimeId}>
                <div className="plugin-runtime-main">
                  <div>
                    <strong>{contribution.title}</strong>
                    <span>
                      {contribution.version}
                      {` · ${contribution.languages.map((item) => item.name).join("、")}`}
                      {contribution.imported ? t("plugin.imported") : t("plugin.liveDiscover")}
                    </span>
                  </div>
                  <span className={`plugin-state-pill ${contribution.available ? "is-ready" : "is-muted"}`}>
                    {contribution.available ? t("plugin.available") : t("plugin.unavailable")}
                  </span>
                </div>
                <details className="plugin-technical-details">
                  <summary>{t("plugin.techDetails")}</summary>
                  <dl>
                    <div><dt>{t("plugin.runtime")}</dt><dd>{contribution.runtimeId}</dd></div>
                    <div><dt>{t("plugin.protocol")}</dt><dd>{compatibility.protocol}</dd></div>
                    {contribution.release.bundleSha256 && (
                      <div><dt>{t("plugin.bundleDigest")}</dt><dd>{contribution.release.bundleSha256}</dd></div>
                    )}
                  </dl>
                </details>
              </article>
            ))}
          </div>
          {!compatibility.contributions.length && (
            <div className="plugin-empty-state">
              <strong>{t("plugin.noRuntimes")}</strong>
              <p>{t("plugin.noRuntimesHint")}</p>
            </div>
          )}
          <div className="plugin-action-row">
            <button
              type="button"
              data-v1-compatibility-preview="import"
              disabled={!platformEnabled || !runtime.view.managementAvailable || compatibilityBusy !== null}
              onClick={() => void previewCompatibility("import")}
            >
              {compatibilityBusy === "import" ? t("plugin.previewing") : t("plugin.previewImport")}
            </button>
            <button
              type="button"
              data-v1-compatibility-preview="rollback"
              disabled={
                !platformEnabled
                || !runtime.view.managementAvailable
                || !compatibility.import.rollbackAvailable
                || compatibilityBusy !== null
              }
              onClick={() => void previewCompatibility("rollback")}
            >
              {compatibilityBusy === "rollback" ? t("plugin.previewing") : t("plugin.previewRollback")}
            </button>
          </div>
          {!platformEnabled && <small>{t("plugin.enableToSave")}</small>}
          {compatibilityPreview && (
            <div className="plugin-v1-compatibility-preview" data-v1-compatibility-action={compatibilityPreview.action}>
              <p>
                {t("plugin.host.compatPreview", {
                  hash: compatibilityPreview.previewSha256 ?? t("plugin.unavailable"),
                  revision: compatibilityPreview.stateRevision,
                })}
                {compatibilityPreview.targetSnapshotRevision == null ? "" : ` · target ${compatibilityPreview.targetSnapshotRevision}`}
              </p>
              {compatibilityPreview.changes.length
                ? (
                  <ul>
                    {compatibilityPreview.changes.map((change) => (
                      <li key={change.id}>{change.action}: {change.id}</li>
                    ))}
                  </ul>
                )
                : (
                  <p>{t("plugin.host.compatNoChanges")}</p>
                )}
              <button
                type="button"
                data-v1-compatibility-apply={compatibilityPreview.action}
                disabled={!compatibilityPreview.available || compatibilityBusy !== null}
                onClick={() => void applyCompatibility()}
              >
                {t("plugin.host.compatApply", { action: compatibilityPreview.action })}
              </button>
            </div>
          )}
        </section>
      )}
  </div>;
}
