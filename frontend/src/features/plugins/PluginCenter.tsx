import { useEffect, useMemo, useRef, useState } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import PluginAdvanced from "./PluginAdvanced.js";
import PluginDetail from "./PluginDetail.js";
import PluginInstallFlow from "./PluginInstallFlow.js";
import { MarketplacePanel } from "./PluginManagementSections.js";
import { filterPlugins, pluginStatus, type PluginFilter } from "./pluginCenterModel.js";
import { localizePluginContribution } from "./pluginLocalization.js";
import { usePluginDetail } from "./usePluginDetail.js";
import type { PluginMarketplaceStatus, PluginPlatformRuntime } from "./pluginPlatformTypes.js";

export type PluginCenterSection = "installed" | "discover" | "advanced" | "install";

export function PluginSettingsPanel({ runtime, onClose, initialSection = "installed" }: {
  runtime: PluginPlatformRuntime; onClose?: () => void; initialSection?: PluginCenterSection;
}) {
  const locale = useLocale();
  const [section, setSection] = useState<PluginCenterSection>(initialSection);
  const [installBusy, setInstallBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<PluginFilter>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mobileDetail, setMobileDetail] = useState(false);
  const [marketplaceStatus, setMarketplaceStatus] = useState<PluginMarketplaceStatus | null>(null);
  const [marketplaceBusy, setMarketplaceBusy] = useState<string | null>(null);
  const [marketplaceError, setMarketplaceError] = useState<string | null>(null);
  const panel = useRef<HTMLDivElement>(null);
  const marketRequest = useRef(0);
  const { openManager, closeManager } = runtime.actions;
  useEffect(() => { openManager(); return closeManager; }, [openManager, closeManager]);
  useEffect(() => {
    if (!onClose) return;
    const previous = document.activeElement;
    panel.current?.focus();
    return () => { if (previous instanceof HTMLElement && previous.isConnected) previous.focus(); };
  }, [onClose]);
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
      if (marketRequest.current === request) setMarketplaceError(error instanceof Error ? error.message : String(error));
    });
    return () => { marketRequest.current += 1; };
  }, [section, platformEnabled, management, loadMarket]);
  const navigate = (next: PluginCenterSection) => { if (installBusy) return; setSection(next); setQuery(""); };
  const runMarketplace = async (key: string, operation: () => Promise<void>) => {
    if (marketplaceBusy) return;
    setMarketplaceBusy(key);
    setMarketplaceError(null);
    try { await operation(); setMarketplaceStatus(await loadMarket()); await detailState.reload(); }
    catch (error) { setMarketplaceError(error instanceof Error ? error.message : String(error)); }
    finally { setMarketplaceBusy(null); }
  };
  const content = <div className="plugin-center" data-testid="plugin-manager" ref={panel} tabIndex={-1}
    role={onClose ? "dialog" : undefined} aria-modal={onClose ? true : undefined} aria-label={t("plugin.title")} inert={!!runtime.view.openSettingsId}
    onKeyDown={(event) => {
      if (!onClose || runtime.view.openSettingsId) return;
      if (event.key === "Escape") { event.stopPropagation(); if (installBusy) return; if (section === "install") navigate("installed"); else onClose(); }
      if (event.key === "Tab") {
        const elements = Array.from(panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex="0"]') ?? []).filter((element) => element.getClientRects().length > 0);
        const first = elements[0]; const last = elements.at(-1);
        if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && (document.activeElement === last || document.activeElement === panel.current)) { event.preventDefault(); first?.focus(); }
      }
    }}>
    <header className="pc-header">
      <div>{onClose && <button className="pc-return" type="button" disabled={installBusy} onClick={onClose}>{t("pc.back")}</button>}<h2>{t("plugin.title")}</h2></div>
      <div className="pc-header-actions"><button type="button" disabled={runtime.view.loading || installBusy} onClick={() => void runtime.actions.refresh().then(() => detailState.reload()).catch(() => undefined)}>{t("alert.refresh")}</button>
        {platformEnabled && <button type="button" className="pc-primary" disabled={installBusy} onClick={() => navigate("install")}>{t("pc.install")}</button>}
        {onClose && <button type="button" disabled={installBusy} onClick={onClose}>{t("export.closeBtn")}</button>}
      </div>
    </header>
    <nav className="pc-navigation" aria-label={t("plugin.title")}>{(["installed", "discover", "advanced"] as const).map((item) => <button type="button" disabled={installBusy} key={item} aria-current={section === item ? "page" : undefined} onClick={() => navigate(item)}>{t(`pc.${item}`)}{item === "installed" && <span>{plugins.length}</span>}</button>)}</nav>
    {!management && <div className="pc-message" role="status">{t("pc.readonly")}</div>}
    {!platformEnabled && runtime.view.catalog && <div className="pc-message">{t("plugin.enableToSave")}</div>}
    {runtime.view.error && <div className="pc-message pc-error" role="alert">{runtime.view.error}</div>}
    {runtime.view.notice && <div className="pc-message" role="status"><span>{runtime.view.notice}</span><button type="button" onClick={runtime.actions.clearNotice}>{t("export.closeBtn")}</button></div>}
    {(section === "installed" || section === "discover") && <div className="pc-tools">
      <input type="search" aria-label={t("pc.search")} placeholder={t("pc.search")} value={query} onChange={(event) => { setQuery(event.target.value); setMobileDetail(false); }} />
      {section === "installed" && <select aria-label={t("pc.filter")} value={filter} onChange={(event) => { setFilter(event.target.value as PluginFilter); setMobileDetail(false); }}>{(["all", "active", "disabled", "attention"] as const).map((value) => <option key={value} value={value}>{t(value === "all" ? "trade.all" : `pc.${value}`)}</option>)}</select>}
    </div>}
    <div className="pc-content">
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
            {query || filter !== "all" ? <button type="button" onClick={() => { setQuery(""); setFilter("all"); }}>{t("interval.clear")}</button> : platformEnabled && <button type="button" onClick={() => navigate("install")}>{t("pc.install")}</button>}
          </div>}
        </div>
        {engines.length > 0 && filter === "all" && <section className="pc-engines"><header><div><h3>{t("plugin.scriptRuntimes")}</h3><p>{t("pc.enginesHint")}</p></div><span>{engines.length}</span></header>
          <div className="pc-engine-grid">{engines.map((engine) => <article key={engine.id} data-v1-runtime={engine.runtimeId}>
            <div><strong>{engine.title}</strong><span className={`plugin-state-pill ${engine.available ? "is-ready" : "is-muted"}`}>{engine.available ? t("plugin.available") : t("plugin.unavailable")}</span></div>
            <p>{engine.languages.map((item) => item.name).join(" · ")} · {engine.version}</p>
            <details className="plugin-technical-details"><summary>{t("plugin.techDetails")}</summary><dl><dt>{t("plugin.runtime")}</dt><dd>{engine.runtimeId}</dd><dt>{t("plugin.protocol")}</dt><dd>{engine.protocol}</dd></dl></details>
          </article>)}</div>
        </section>}
      </>}
      {section === "discover" && <>
        {marketplaceError && <div className="pc-message pc-error" role="alert">{marketplaceError}<button type="button" onClick={() => void runMarketplace("refresh-status", () => runtime.actions.refresh())}>{t("shell.retry")}</button></div>}
        {platformEnabled ? <MarketplacePanel runtime={runtime} status={management ? marketplaceStatus : null} busy={marketplaceBusy} run={runMarketplace} query={query} /> : <p>{t("plugin.enableToSave")}</p>}
      </>}
      {section === "advanced" && <PluginAdvanced runtime={runtime} />}
      {section === "install" && platformEnabled && <PluginInstallFlow runtime={runtime} onPendingChange={setInstallBusy} onDone={() => { navigate("installed"); setFilter("all"); }} />}
    </div>
  </div>;
  return onClose ? <div className="pc-overlay">{content}</div> : content;
}
