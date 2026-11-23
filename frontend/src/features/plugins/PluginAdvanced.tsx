import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { RuntimeRegistryPanel } from "./PluginManagementSections.js";
import type { PluginPlatformRuntime } from "./pluginPlatformTypes.js";
export default function PluginAdvanced({ runtime }: { runtime: PluginPlatformRuntime }) {
  useLocale();
  const platformEnabled = runtime.view.catalog?.platform.enabled === true;
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
  </div>;
}
