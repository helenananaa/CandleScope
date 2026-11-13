import { Button } from "../ui/Button.js";
import { Checkbox, Field, Input, Select } from "../ui/Field.js";
import { Disclosure, InlineAlert } from "../ui/Display.js";
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
    /** Edits that 保存 has not sent yet. */
    proxyDirty?: boolean;
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
    proxyDirty = false,
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
    const testTone = proxyTestResult?.success ? "success" : proxyTestResult?.partial ? "warning" : "danger";
    return (
        <div className="st-group st-proxy">
            <div className="st-group-title">{t("settings.proxy.title")}</div>
            <div className="st-group-desc">{t("settings.proxy.desc")}</div>
            <div className="st-theme-grid st-proxy-mode-grid">
                {PROXY_MODES.map((mode) => (
                    <button
                        key={mode.value}
                        type="button"
                        className={`st-theme-card ${proxyMode === mode.value ? 'active' : ''}`}
                        aria-pressed={proxyMode === mode.value}
                        onClick={() => onProxyModeChange(mode.value)}
                    >
                        <span className="st-theme-icon"><Icon name={mode.icon} size={22} /></span>
                        <span className="st-theme-label">{t(mode.labelKey)}</span>
                    </button>
                ))}
            </div>

            {proxyMode === 'system' && systemProxy && (
                <dl className="st-kv">
                    <dt>{t("settings.proxy.detected")}</dt>
                    <dd><code>{systemProxy}</code></dd>
                </dl>
            )}
            {proxyMode === 'system' && !systemProxy && (
                <InlineAlert tone="warning">{t("settings.proxy.notDetected")}</InlineAlert>
            )}

            {proxyMode === 'custom' && (
                <Field label={t("settings.proxy.address")}>
                    <Input
                        placeholder={t("settings.proxy.placeholder")}
                        value={customProxy}
                        onChange={(event) => onCustomProxyChange(event.target.value)}
                    />
                </Field>
            )}

            {proxyMode === 'pool' && (
                <div className="st-proxy-pool">
                    <Field label={t("settings.proxy.strategy")} hint={t("settings.proxy.poolHelp")}>
                        <Select value={proxyStrategy} disabled={proxyLoading}
                            onChange={(event) => onProxyStrategyChange?.(event.target.value === "balanced" ? "balanced" : "failover")}>
                            <option value="failover">{t("settings.proxy.failover")}</option>
                            <option value="balanced">{t("settings.proxy.balanced")}</option>
                        </Select>
                    </Field>
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
                                <Field label={t("settings.proxy.name")}>
                                    <Input value={route.name} onChange={(event) => updateRoute(route.id, { name: event.target.value })} />
                                </Field>
                                <Field label={t("settings.proxy.address")}>
                                    <Input type="password" autoComplete="off" placeholder="http://127.0.0.1:7890" value={route.url}
                                        onChange={(event) => updateRoute(route.id, { url: event.target.value })} />
                                </Field>
                                <Field label={t("settings.proxy.egressGroup")}>
                                    <Input value={route.egress_group} onChange={(event) => updateRoute(route.id, { egress_group: event.target.value })} />
                                </Field>
                                <Field label={t("settings.proxy.concurrency")} hint={t("settings.proxy.archiveConcurrency", { count: Math.max(0, route.max_concurrency - 1) })}>
                                    <Input type="number" min={1} max={32} value={route.max_concurrency}
                                        onChange={(event) => updateRoute(route.id, { max_concurrency: Number(event.target.value) })} />
                                </Field>
                                <Field label={t("settings.proxy.wsCapacity")}>
                                    <Input type="number" min={1} max={4096} value={route.max_ws_subscriptions ?? 64}
                                        onChange={(event) => updateRoute(route.id, { max_ws_subscriptions: Number(event.target.value) })} />
                                </Field>
                                <Field label={t("settings.proxy.exchanges")}>
                                    <Input value={route.exchanges.join(", ")}
                                        onChange={(event) => updateRoute(route.id, { exchanges: event.target.value.split(",").map((value) => value.trim()).filter(Boolean) })} />
                                </Field>
                            </div>
                            <div className="st-proxy-route-actions">
                                <Checkbox label={t("settings.proxy.enabled")} checked={route.enabled}
                                    onChange={(event) => updateRoute(route.id, { enabled: event.target.checked })} />
                                {index > 0 && <Button size="sm" onClick={() => onProxyRoutesChange?.([route, ...proxyRoutes.filter((value) => value.id !== route.id)])}>
                                    {t("settings.proxy.makePrimary")}</Button>}
                                <Button size="sm" variant="ghost" onClick={() => onProxyRoutesChange?.(proxyRoutes.filter((value) => value.id !== route.id))}>
                                    {t("settings.proxy.remove")}</Button>
                            </div>
                            <Disclosure summary={t("settings.proxy.routeStatus")}>
                                <div className="st-proxy-status" role="status">
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
                            </Disclosure>
                        </fieldset>;
                    })}
                    <div>
                        <Button disabled={proxyLoading || proxyRoutes.length >= 16}
                            onClick={() => onProxyRoutesChange?.([...proxyRoutes, { id: crypto.randomUUID(), name: "", url: "",
                                egress_group: "shared", enabled: true, exchanges: [], max_concurrency: 4, max_ws_subscriptions: 64 }])}>
                            {t("settings.proxy.add")}
                        </Button>
                    </div>
                </div>
            )}

            {effectiveProxy && proxyMode !== 'none' && (
                <dl className="st-kv">
                    <dt>{t("settings.proxy.effective")}</dt>
                    <dd><code>{effectiveProxy}</code></dd>
                </dl>
            )}

            <div className="st-form-actions">
                <Button onClick={onProxyTest} disabled={proxyLoading}>
                    {proxyLoading ? t("settings.proxy.testing") : t("settings.proxy.test")}
                </Button>
                <Button variant="primary" onClick={onProxySave} disabled={proxyLoading || !proxyDirty}>
                    {proxyLoading ? t("settings.proxy.saving") : t("settings.proxy.save")}
                </Button>
                {proxyDirty && <span className="st-unsaved">{t("settings.unsaved.badge")}</span>}
            </div>

            {proxySaveMsg && (
                <InlineAlert tone={proxySaveMsg.ok ? "success" : "danger"}>{proxySaveMsg.text}</InlineAlert>
            )}

            {proxyTestResult && (
                <div className="st-proxy-results">
                    <InlineAlert tone={testTone} title={t("settings.proxy.exchangeNetwork")}>
                        {proxyTestResult.message}
                        {proxyTestResult.proxy_used && (
                            <div className="st-result-detail">{t("settings.proxy.used", { proxy: proxyTestResult.proxy_used })}</div>
                        )}
                    </InlineAlert>
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
                    <InlineAlert tone={proxyTestResult.data_engine === "ready" ? "success" : "warning"} title={t("settings.proxy.dataEngine")}>
                        {t(proxyTestResult.data_engine === "ready" ? "settings.proxy.engineReady"
                            : proxyTestResult.data_engine === "not_initialized" || proxyTestResult.data_engine === "not_started" ? "settings.proxy.engineNotReady"
                            : proxyTestResult.data_engine === "error" ? "settings.proxy.engineError" : "settings.proxy.engineUnknown")}
                        <div className="st-result-detail">{t("settings.proxy.engineScope")}</div>
                    </InlineAlert>
                </div>
            )}
        </div>
    );
}
