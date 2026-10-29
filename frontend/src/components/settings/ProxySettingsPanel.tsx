import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { Icon } from "../icons/Icon.js";
import type { IconName } from "../icons/Icon.js";
import type {
    ProxyMode,
    ProxySaveMessage,
    ProxyTestResult,
    ProxyRouteConfig,
    ProxyPoolStatus,
} from "../../features/settings/proxySettingsRuntime.js";

interface ProxyModeOption {
    value: ProxyMode;
    icon: IconName;
    labelKey: "settings.proxy.system" | "settings.proxy.custom" | "settings.proxy.none" | "settings.proxy.pool";
}

const PROXY_MODES: ProxyModeOption[] = [
    { value: 'system', icon: 'monitor', labelKey: 'settings.proxy.system' },
    { value: 'custom', icon: 'sliders', labelKey: 'settings.proxy.custom' },
    { value: 'none', icon: 'ban', labelKey: 'settings.proxy.none' },
    { value: 'pool', icon: 'exchange', labelKey: 'settings.proxy.pool' },
];

export interface ProxySettingsPanelProps {
    proxyMode: ProxyMode;
    customProxy: string;
    systemProxy: string;
    effectiveProxy: string;
    proxyLoading: boolean;
    proxyTestResult: ProxyTestResult | null;
    proxySaveMsg: ProxySaveMessage | null;
    onProxyModeChange(mode: ProxyMode): void;
    onCustomProxyChange(value: string): void;
    onProxyTest(): void;
    onProxySave(): void;
    proxyRoutes?: ProxyRouteConfig[];
    proxySavedRoutes?: ProxyRouteConfig[];
    proxyStrategy?: "failover" | "balanced";
    proxyPoolStatus?: ProxyPoolStatus | null;
    onProxyRoutesChange?(routes: ProxyRouteConfig[]): void;
    onProxyStrategyChange?(strategy: "failover" | "balanced"): void;
}

export default function ProxySettingsPanel({
    proxyMode,
    customProxy,
    systemProxy,
    effectiveProxy,
    proxyLoading,
    proxyTestResult,
    proxySaveMsg,
    onProxyModeChange,
    onCustomProxyChange,
    onProxyTest,
    onProxySave,
    proxyRoutes = [], proxySavedRoutes, proxyStrategy = "failover", proxyPoolStatus,
    onProxyRoutesChange, onProxyStrategyChange,
}: ProxySettingsPanelProps) {
    useLocale();
    const updateRoute = (id: string, patch: Partial<ProxyRouteConfig>) => {
        onProxyRoutesChange?.(proxyRoutes.map((route) => route.id === id ? { ...route, ...patch } : route));
    };
    return (
        <div className="st-group">
            <div className="st-group-title">{t("settings.proxy.title")}</div>
            <div className="st-group-desc">{t("settings.proxy.desc")}</div>
            <div className="st-theme-grid st-proxy-mode-grid">
                {PROXY_MODES.map((mode) => (
                    <button
                        key={mode.value}
                        className={`st-theme-card ${proxyMode === mode.value ? 'active' : ''}`}
                        onClick={() => onProxyModeChange(mode.value)}
                    >
                        <span className="st-theme-icon"><Icon name={mode.icon} size={22} /></span>
                        <span className="st-theme-label">{t(mode.labelKey)}</span>
                    </button>
                ))}
            </div>

            {proxyMode === 'system' && systemProxy && (
                <div className="st-info-box">
                    <span className="st-info-label">{t("settings.proxy.detected")}</span>
                    <code className="st-info-value">{systemProxy}</code>
                </div>
            )}
            {proxyMode === 'system' && !systemProxy && (
                <div className="st-info-box st-info-warn">
                    <span>{t("settings.proxy.notDetected")}</span>
                </div>
            )}

            {proxyMode === 'custom' && (
                <div style={{ marginTop: 12 }}>
                    <input
                        type="text"
                        className="st-input"
                        placeholder={t("settings.proxy.placeholder")}
                        value={customProxy}
                        onChange={(event) => onCustomProxyChange(event.target.value)}
                    />
                </div>
            )}

            {proxyMode === 'pool' && (
                <div className="st-proxy-pool">
                    <label className="st-proxy-field">
                        <span>{t("settings.proxy.strategy")}</span>
                        <select className="st-input" value={proxyStrategy} disabled={proxyLoading}
                            onChange={(event) => onProxyStrategyChange?.(event.target.value === "balanced" ? "balanced" : "failover")}>
                            <option value="failover">{t("settings.proxy.failover")}</option>
                            <option value="balanced">{t("settings.proxy.balanced")}</option>
                        </select>
                    </label>
                    <p className="st-group-desc">{t("settings.proxy.poolHelp")}</p>
                    {proxyRoutes.map((route, index) => {
                        const saved = proxySavedRoutes?.find((item) => item.id === route.id);
                        const matchesSaved = !proxySavedRoutes || (saved && saved.url === route.url
                            && saved.egress_group === route.egress_group && saved.enabled === route.enabled
                            && saved.max_concurrency === route.max_concurrency
                            && (saved.max_ws_subscriptions ?? 64) === (route.max_ws_subscriptions ?? 64)
                            && saved.exchanges.join(",") === route.exchanges.join(","));
                        const status = matchesSaved ? proxyPoolStatus?.routes?.find((row) => row.id === route.id) : undefined;
                        const cooldown = status ? Math.max(0, ...Object.values(status.budgets).map((budget) =>
                            Math.max(budget.cooldown_remaining_seconds ?? 0, budget.global_circuit?.cooldown_remaining_seconds ?? 0)),
                            ...status.observations.map((item) => item.cooldown_seconds)) : 0;
                        return <fieldset className="st-proxy-route" key={route.id} disabled={proxyLoading}>
                            <legend>{t("settings.proxy.route", { index: index + 1 })}</legend>
                            <div className="st-proxy-fields">
                                <label className="st-proxy-field"><span>{t("settings.proxy.name")}</span>
                                    <input className="st-input" value={route.name} onChange={(event) => updateRoute(route.id, { name: event.target.value })} /></label>
                                <label className="st-proxy-field"><span>{t("settings.proxy.address")}</span>
                                    <input type="password" autoComplete="off" className="st-input" placeholder="http://127.0.0.1:7890" value={route.url}
                                        onChange={(event) => updateRoute(route.id, { url: event.target.value })} /></label>
                                <label className="st-proxy-field"><span>{t("settings.proxy.egressGroup")}</span>
                                    <input className="st-input" value={route.egress_group} onChange={(event) => updateRoute(route.id, { egress_group: event.target.value })} /></label>
                                <label className="st-proxy-field"><span>{t("settings.proxy.concurrency")} · {t("settings.proxy.archiveConcurrency", { count: Math.max(0, route.max_concurrency - 1) })}</span>
                                    <input type="number" min={1} max={32} className="st-input" value={route.max_concurrency}
                                        onChange={(event) => updateRoute(route.id, { max_concurrency: Number(event.target.value) })} /></label>
                                <label className="st-proxy-field"><span>{t("settings.proxy.wsCapacity")}</span>
                                    <input type="number" min={1} max={4096} className="st-input" value={route.max_ws_subscriptions ?? 64}
                                        onChange={(event) => updateRoute(route.id, { max_ws_subscriptions: Number(event.target.value) })} /></label>
                                <label className="st-proxy-field"><span>{t("settings.proxy.exchanges")}</span>
                                    <input className="st-input" value={route.exchanges.join(", ")}
                                        onChange={(event) => updateRoute(route.id, { exchanges: event.target.value.split(",").map((value) => value.trim()).filter(Boolean) })} /></label>
                            </div>
                            <div className="st-actions-row">
                                <label><input type="checkbox" checked={route.enabled}
                                    onChange={(event) => updateRoute(route.id, { enabled: event.target.checked })} /> {t("settings.proxy.enabled")}</label>
                                {index > 0 && <button className="st-btn st-btn-secondary" onClick={() => onProxyRoutesChange?.([route, ...proxyRoutes.filter((value) => value.id !== route.id)])}>
                                    {t("settings.proxy.makePrimary")}</button>}
                                <button className="st-btn st-btn-secondary" onClick={() => onProxyRoutesChange?.(proxyRoutes.filter((value) => value.id !== route.id))}>
                                    {t("settings.proxy.remove")}</button>
                            </div>
                            <div className="st-result-detail" role="status">
                                {status && <div>{t("settings.proxy.active", { count: status.active_requests })}</div>}
                                {status?.ws_subscriptions !== undefined && <div>{t("settings.proxy.wsLoad", {
                                    count: status.ws_subscriptions, capacity: status.max_ws_subscriptions ?? 64,
                                })}</div>}
                                {status?.ws_sessions !== undefined && <div>{t("settings.proxy.wsSessions", { count: status.ws_sessions })}</div>}
                                {status?.native_websockets !== undefined && status.ccxt_physical_websockets !== undefined && <div>{t("settings.proxy.physicalWs", {
                                    count: status.native_websockets + status.ccxt_physical_websockets,
                                })}</div>}
                                {status?.ws_traffic && <>
                                    <div>{t("settings.proxy.wsFlow", {
                                        messages: status.ws_traffic.messages_per_second.toFixed(1),
                                        kib: (status.ws_traffic.payload_bytes_per_second / 1024).toFixed(1),
                                        seconds: status.ws_traffic.window_seconds,
                                    })}</div>
                                    {status.ws_traffic.queue_capacity > 0 && <div>{t("settings.proxy.wsQueue", {
                                        count: status.ws_traffic.queue_size, capacity: status.ws_traffic.queue_capacity,
                                    })}</div>}
                                    <div>{t("settings.proxy.wsDisconnects", {
                                        count: status.ws_traffic.disconnects_recent, seconds: status.ws_traffic.window_seconds,
                                    })}</div>
                                    {status.ws_traffic.last_message_age_seconds !== null && <div>{t("settings.proxy.wsLastMessage", {
                                        seconds: Math.floor(status.ws_traffic.last_message_age_seconds),
                                    })}</div>}
                                    <div>{t("settings.proxy.wsTrafficHelp")}</div>
                                </>}
                                {!status?.observations.length ? t("settings.proxy.unobserved") : <>
                                    {status.observations.map((item) => <div key={`${item.exchange}:${item.kind}`}>
                                        {item.exchange} · {item.kind.startsWith("archive:") ? `ZIP · ${item.kind.slice(8)}` : item.kind === "ws" ? "WS" : "REST"}{item.latency_ms !== null && <> · {t("settings.proxy.latency", { ms: Math.round(item.latency_ms) })}</>} · {t("settings.proxy.failures", { count: item.failures })}
                                    </div>)}
                                </>}
                                {cooldown > 0 && <div>{t("settings.proxy.cooldown", { seconds: Math.ceil(cooldown) })}</div>}
                            </div>
                        </fieldset>;
                    })}
                    <button className="st-btn st-btn-secondary" disabled={proxyLoading || proxyRoutes.length >= 16}
                        onClick={() => onProxyRoutesChange?.([...proxyRoutes, { id: crypto.randomUUID(), name: "", url: "",
                            egress_group: "shared", enabled: true, exchanges: [], max_concurrency: 4, max_ws_subscriptions: 64 }])}>
                        {t("settings.proxy.add")}
                    </button>
                </div>
            )}

            {effectiveProxy && proxyMode !== 'none' && (
                <div className="st-info-box">
                    <span className="st-info-label">{t("settings.proxy.effective")}</span>
                    <code className="st-info-value">{effectiveProxy}</code>
                </div>
            )}

            <div className="st-actions-row">
                <button
                    className="st-btn st-btn-secondary"
                    onClick={onProxyTest}
                    disabled={proxyLoading}
                >
                    {proxyLoading ? t("settings.proxy.testing") : t("settings.proxy.test")}
                </button>
                <button
                    className="st-btn st-btn-primary"
                    onClick={onProxySave}
                    disabled={proxyLoading}
                >
                    {proxyLoading ? t("settings.proxy.saving") : t("settings.proxy.save")}
                </button>
            </div>

            {proxyTestResult && (
                <>
                <div className={`st-result ${proxyTestResult.success ? 'st-result-ok' : proxyTestResult.partial ? 'st-result-warn' : 'st-result-fail'}`}>
                    <strong>{t("settings.proxy.exchangeNetwork")}</strong><br />
                    <span className="st-result-message"><Icon name={proxyTestResult.success ? "check" : proxyTestResult.partial ? "warning" : "error"} size={14} /> {proxyTestResult.message}</span>
                    {proxyTestResult.proxy_used && (
                        <div className="st-result-detail">{t("settings.proxy.used", { proxy: proxyTestResult.proxy_used })}</div>
                    )}
                    {Array.isArray(proxyTestResult.results) && proxyTestResult.results.length > 0 && (
                        <div className="st-exchange-results">
                            {proxyTestResult.results.map((result) => (
                                <div key={`${String(result.route_id ?? "")}:${result.exchange}`} className={`st-exchange-result-item ${result.success ? 'ok' : 'fail'}`}>
                                    <span className="st-exchange-result-icon"><Icon name={result.success ? "check" : "error"} size={14} /></span>
                                    <span className="st-exchange-result-label">{result.label}</span>
                                    <span className="st-exchange-result-msg">{result.message}</span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
                <div className={`st-result ${proxyTestResult.data_engine === "ready" ? "st-result-ok" : "st-result-warn"}`}>
                    <strong>{t("settings.proxy.dataEngine")}</strong>
                    <div>{t(proxyTestResult.data_engine === "ready" ? "settings.proxy.engineReady"
                        : proxyTestResult.data_engine === "not_initialized" || proxyTestResult.data_engine === "not_started" ? "settings.proxy.engineNotReady"
                        : proxyTestResult.data_engine === "error" ? "settings.proxy.engineError" : "settings.proxy.engineUnknown")}</div>
                    <div className="st-result-detail">{t("settings.proxy.engineScope")}</div>
                </div>
                </>
            )}

            {proxySaveMsg && (
                <div className={`st-result ${proxySaveMsg.ok ? 'st-result-ok' : 'st-result-fail'}`}>
                    <span>{proxySaveMsg.text}</span>
                </div>
            )}
        </div>
    );
}
