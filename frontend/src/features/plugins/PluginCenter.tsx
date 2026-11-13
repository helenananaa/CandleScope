import { Button } from "../../components/ui/Button.js";
import { Badge, InlineAlert } from "../../components/ui/Display.js";
import { Input, Select } from "../../components/ui/Field.js";
import { TabPanel, Tabs } from "../../components/ui/Choice.js";
import { describeError } from "../../i18n/serverErrors.js";
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import PluginAdvanced from "./PluginAdvanced.js";
import ExtensionManager from "../extensions/ExtensionManager.js";
import { useExtensionText } from "../extensions/hooks.js";
import PluginDetail from "./PluginDetail.js";
import PluginInstallFlow from "./PluginInstallFlow.js";
import { MarketplacePanel } from "./PluginManagementSections.js";
import { filterPlugins, pluginStatus, type PluginFilter } from "./pluginCenterModel.js";
import { localizePluginContribution } from "./pluginLocalization.js";
import { usePluginDetail } from "./usePluginDetail.js";
import type { PluginMarketplaceStatus, PluginPlatformRuntime } from "./pluginPlatformTypes.js";

export type PluginCenterSection = "installed" | "discover" | "advanced" | "install" | "extensions";

const TABS = ["installed", "discover", "advanced", "extensions"] as const;

/**
 * The plugin center, shown in Settings → 插件与扩展. While a plugin installs, `onBusyChange`
 * tells Settings to stay open.
 */
export function PluginSettingsPanel({ runtime, initialSection = "installed", onBusyChange }: {
  runtime: PluginPlatformRuntime; initialSection?: PluginCenterSection; onBusyChange?: (busy: boolean) => void;
}) {
  const locale = useLocale();
  const extensionText = useExtensionText();
  const [section, setSection] = useState<PluginCenterSection>(initialSection);
  const [installBusy, setInstallBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<PluginFilter>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mobileDetail, setMobileDetail] = useState(false);
  const [marketplaceStatus, setMarketplaceStatus] = useState<PluginMarketplaceStatus | null>(null);
  const [marketplaceBusy, setMarketplaceBusy] = useState<string | null>(null);
  const [marketplaceError, setMarketplaceError] = useState<string | null>(null);
  const tabsId = useId();
  const marketRequest = useRef(0);
  const { openManager, closeManager } = runtime.actions;
  useEffect(() => { openManager(); return closeManager; }, [openManager, closeManager]);
  useEffect(() => {
    onBusyChange?.(installBusy);
    return () => onBusyChange?.(false);
  }, [installBusy, onBusyChange]);
  const plugins = useMemo(() => (runtime.view.catalog?.plugins ?? []).map((plugin) => ({
    ...plugin, contributions: plugin.contributions.map((item) => localizePluginContribution(item, locale)),
  })), [runtime.view.catalog?.plugins, locale]);
  const visible = filterPlugins(plugins, query, filter);
  const selected = visible.find((item) => item.id === selectedId) ?? visible[0] ?? null;
  const detailState = usePluginDetail(runtime, selected?.id ?? null);
  const compatibility = runtime.view.catalog?.compatibility;
  const engines = (compatibility?.contributions ?? []).filter((item) => `${item.title} ${item.runtimeId} ${item.languages.map((language) => language.name).join(" ")}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const platformEnabled = runtime.view.catalog?.platform.enabled === true;
  const loadMarket = runtime.actions.loadMarketplaceStatus;
  const management = runtime.view.managementAvailable;
  useEffect(() => {
    const request = ++marketRequest.current;
    if (section !== "discover" || !platformEnabled || !management) return;
    setMarketplaceError(null);
    void loadMarket().then((status) => {
      if (marketRequest.current === request) setMarketplaceStatus(status);
    }).catch((error: unknown) => {
      if (marketRequest.current === request) setMarketplaceError(error instanceof Error ? describeError(error, error.message) : String(error));
    });
    return () => { marketRequest.current += 1; };
  }, [section, platformEnabled, management, loadMarket]);
  const navigate = (next: PluginCenterSection) => { if (installBusy) return; setSection(next); setQuery(""); };
  const runMarketplace = async (key: string, operation: () => Promise<void>) => {
    if (marketplaceBusy) return;
    setMarketplaceBusy(key);
    setMarketplaceError(null);
    try { await operation(); setMarketplaceStatus(await loadMarket()); await detailState.reload(); }
    catch (error) { setMarketplaceError(error instanceof Error ? describeError(error, error.message) : String(error)); }
    finally { setMarketplaceBusy(null); }
  };
  const refreshAll = () => void runtime.actions.refresh().then(() => detailState.reload()).catch(() => undefined);
  const sectionBody = (children: ReactNode) => section === "install"
    ? <div className="pc-content">{children}</div>
    : <TabPanel tabsId={tabsId} value={section} className="pc-content">{children}</TabPanel>;
  return <div className="plugin-center" data-testid="plugin-manager" aria-label={t("plugin.title")} inert={!!runtime.view.openSettingsId}
    onKeyDown={(event) => {
      // Escape steps back from the install page before it closes Settings.
      if (event.key !== "Escape" || section !== "install" || installBusy || runtime.view.openSettingsId) return;
      event.preventDefault();
      event.stopPropagation();
      navigate("installed");
    }}>
    <div className="pc-toolbar">
      <Tabs id={tabsId} className="pc-navigation" label={t("plugin.title")} value={section} onChange={navigate}
        tabs={TABS.map((item) => ({
          value: item,
          disabled: installBusy,
          label: item === "extensions" ? extensionText("可信扩展", "Trusted extensions") : t(`pc.${item}`),
          ...(item === "installed" ? { badge: plugins.length } : {}),
        }))} />
      <div className="pc-toolbar-actions">
        <Button size="sm" disabled={runtime.view.loading || installBusy} onClick={refreshAll}>{t("alert.refresh")}</Button>
        {platformEnabled && management && <Button size="sm" variant="primary" disabled={installBusy} onClick={() => navigate("install")}>{t("pc.install")}</Button>}
      </div>
    </div>
    {!management && <InlineAlert>{t("pc.readonly")}</InlineAlert>}
    {!platformEnabled && runtime.view.catalog && <InlineAlert>{t("plugin.enableToSave")}</InlineAlert>}
    {runtime.view.error && <InlineAlert tone="danger">{runtime.view.error}</InlineAlert>}
    {runtime.view.notice && <InlineAlert action={<Button size="sm" variant="ghost" onClick={runtime.actions.clearNotice}>{t("export.closeBtn")}</Button>}>{runtime.view.notice}</InlineAlert>}
    {(section === "installed" || section === "discover") && <div className="pc-tools">
      <Input type="search" aria-label={t("pc.search")} placeholder={t("pc.search")} value={query} onChange={(event) => { setQuery(event.target.value); setMobileDetail(false); }} />
      {section === "installed" && <Select aria-label={t("pc.filter")} value={filter} onChange={(event) => { setFilter(event.target.value as PluginFilter); setMobileDetail(false); }}>{(["all", "active", "disabled", "attention"] as const).map((value) => <option key={value} value={value}>{t(value === "all" ? "trade.all" : `pc.${value}`)}</option>)}</Select>}
    </div>}
    {sectionBody(<>
      {runtime.view.loading && !runtime.view.catalog && <p role="status">{t("plugin.loadingDetail")}</p>}
      {section === "installed" && runtime.view.catalog && <>
        <div className={`pc-library ${mobileDetail ? "pc-show-detail" : ""} ${visible.length ? "" : "pc-library-empty"}`}>
          {visible.length > 0 ? <>
            <nav className="pc-list" aria-label={t("pc.installed")}>{visible.map((plugin) => <button type="button" key={plugin.id} aria-current={selected?.id === plugin.id ? "true" : undefined} onClick={() => { setSelectedId(plugin.id); setMobileDetail(true); }}>
              <span className="pc-list-title">{plugin.name}</span><span>{plugin.publisher} · {plugin.version}</span><small>{t(`pc.${pluginStatus(plugin)}`)}</small>
            </button>)}</nav>
            {selected && <PluginDetail key={selected.id} selected={selected} {...detailState} runtime={runtime} onBack={() => setMobileDetail(false)} onDiscover={() => navigate("discover")} />}
          </> : <div className="pc-empty"><h3>{query || filter !== "all" ? t("pc.noResults") : t("plugin.empty")}</h3>
            <p>{query || filter !== "all" ? t("pc.search") : t("pc.emptyHint")}</p>
            {query || filter !== "all" ? <Button onClick={() => { setQuery(""); setFilter("all"); }}>{t("interval.clear")}</Button> : platformEnabled && management && <Button variant="primary" onClick={() => navigate("install")}>{t("pc.install")}</Button>}
          </div>}
        </div>
        {engines.length > 0 && filter === "all" && <section className="pc-engines"><header><div><h3>{t("plugin.scriptRuntimes")}</h3><p>{t("pc.enginesHint")}</p></div><span>{engines.length}</span></header>
          {engines.some((engine) => !engine.available) && <p role="status">{t("plugin.unavailable")}: {engines.filter((engine) => !engine.available).map((engine) => engine.title).join(", ")}. {t("native.platformHelp")}</p>}
          <div className="pc-engine-grid">{engines.map((engine) => <article key={engine.id} data-v1-runtime={engine.runtimeId}>
            <div><strong>{engine.title}</strong><Badge tone={engine.available ? "success" : "neutral"}>{engine.available ? t("plugin.available") : t("plugin.unavailable")}</Badge></div>
            <p>{engine.languages.map((item) => item.name).join(" · ")} · {engine.version}</p>
            <details className="plugin-technical-details"><summary>{t("plugin.techDetails")}</summary><dl><dt>{t("plugin.runtime")}</dt><dd>{engine.runtimeId}</dd><dt>{t("plugin.protocol")}</dt><dd>{engine.protocol}</dd></dl></details>
          </article>)}</div>
        </section>}
      </>}
      {section === "discover" && <>
        {marketplaceError && <InlineAlert tone="danger" action={<Button size="sm" onClick={() => void runMarketplace("refresh-status", () => runtime.actions.refresh())}>{t("shell.retry")}</Button>}>{marketplaceError}</InlineAlert>}
        {platformEnabled ? <MarketplacePanel runtime={runtime} status={management ? marketplaceStatus : null} busy={marketplaceBusy} run={runMarketplace} query={query} /> : <p>{t("plugin.enableToSave")}</p>}
      </>}
      {section === "extensions" && <ExtensionManager />}
      {section === "advanced" && <PluginAdvanced runtime={runtime} />}
      {section === "install" && platformEnabled && <PluginInstallFlow runtime={runtime} onPendingChange={setInstallBusy} onDone={() => { navigate("installed"); setFilter("all"); }} />}
    </>)}
  </div>;
}
