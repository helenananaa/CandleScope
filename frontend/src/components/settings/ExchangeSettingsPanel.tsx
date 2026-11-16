import { useMemo, useState } from "react";
import {
    t,
    type MessageKey,
} from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import type {
    CcxtCatalogSummaryPayload,
    ExchangeCapabilityPayload,
    ExchangeChannelCapabilityPayload,
    ExchangeMarketPayload,
} from "../../features/settings/exchangeSettingsRuntime.js";
import {
    exchangeChannelsForMarket,
    exchangeHasDerivatives,
    exchangeIsPollingOnly,
    exchangeIsRoutable,
    exchangeMarketCheckKey,
    exchangeProductSurfaces,
    exchangeProvider,
    filterExchangeCapabilities,
    type ExchangeConnectionCheck,
    type ExchangeSupportFilter,
} from "../../features/exchange-support/exchangeSupportModel.js";
import { Icon } from "../icons/Icon.js";
import { Button } from "../ui/Button.js";
import { SegmentedControl } from "../ui/Choice.js";
import { Badge, Disclosure, InlineAlert, Stat } from "../ui/Display.js";
import { EmptyState } from "../ui/EmptyState.js";
import { Input } from "../ui/Field.js";

const CHANNEL_ORDER = [
    "kline",
    "trade",
    "agg_trade",
    "ticker",
    "mini_ticker",
    "depth",
    "full_depth",
    "mark_price",
    "index_price",
    "funding_rate",
    "open_interest",
    "basis",
    "liquidation",
];

const CHANNEL_LABELS: Record<string, MessageKey> = {
    kline: "settings.exchange.channel.kline",
    trade: "settings.exchange.channel.trade",
    agg_trade: "settings.exchange.channel.aggTrade",
    ticker: "settings.exchange.channel.ticker",
    mini_ticker: "settings.exchange.channel.miniTicker",
    depth: "settings.exchange.channel.depth",
    full_depth: "settings.exchange.channel.fullDepth",
    mark_price: "settings.exchange.channel.markPrice",
    index_price: "settings.exchange.channel.indexPrice",
    funding_rate: "settings.exchange.channel.fundingRate",
    open_interest: "settings.exchange.channel.openInterest",
    basis: "settings.exchange.channel.basis",
    liquidation: "settings.exchange.channel.liquidation",
};

const FILTERS: Array<{ value: ExchangeSupportFilter; label: MessageKey }> = [
    { value: "all", label: "settings.exchange.filter.all" },
    { value: "primary", label: "settings.exchange.filter.primary" },
    { value: "streaming", label: "settings.exchange.filter.streaming" },
    { value: "polling", label: "settings.exchange.filter.polling" },
    { value: "derivatives", label: "settings.exchange.filter.derivatives" },
    { value: "unroutable", label: "settings.exchange.filter.unroutable" },
];

function stringArray(value: unknown): string[] {
    return Array.isArray(value)
        ? value.filter((item): item is string => typeof item === "string" && Boolean(item))
        : [];
}

function channelLabel(channel: string): string {
    const normalized = channel.trim().toLowerCase();
    const key = CHANNEL_LABELS[normalized];
    return key ? t(key) : channel;
}

function providerLabel(provider: string): string {
    if (provider === "ccxt_primary") return t("settings.exchange.provider.primary");
    if (provider === "ccxt_unified") return t("settings.exchange.provider.unified");
    return t("settings.exchange.provider.plugin");
}

function verificationLabel(level: string | undefined): string {
    if (level === "soak") return t("settings.exchange.verification.soak");
    if (level === "shadow") return t("settings.exchange.verification.shadow");
    if (level === "capability_contract") return t("settings.exchange.verification.contract");
    return t("settings.exchange.verification.catalogOnly");
}

function transportLabel(transport: string): string {
    if (transport === "plugin_stream" || transport === "websocket") {
        return t("settings.exchange.transport.ws");
    }
    if (transport === "rest_poll") return t("settings.exchange.transport.poll");
    if (transport === "rest_snapshot") return t("settings.exchange.transport.snapshot");
    if (transport === "rest_history") return t("settings.exchange.transport.history");
    return transport;
}

function formatTransports(value: unknown, supported: boolean): string {
    const transports = stringArray(value);
    if (!supported) return t("settings.exchange.none");
    if (transports.length === 0) return t("settings.exchange.declared");
    return transports.map(transportLabel).join(" + ");
}

function qualityLabel(channel: ExchangeChannelCapabilityPayload): string {
    if (channel.delta === true && channel.sequence !== "none") {
        return t("settings.exchange.quality.strictDepth");
    }
    if (channel.snapshot === true) return t("settings.exchange.quality.snapshot");
    if (channel.delivery === "latest") return t("settings.exchange.quality.lossy");
    if (typeof channel.sequence === "string" && channel.sequence !== "none") {
        return t("settings.exchange.quality.sequence", { sequence: channel.sequence });
    }
    return t("settings.exchange.quality.unsequenced");
}

function configuredValues(channel: ExchangeChannelCapabilityPayload): string[] {
    const params = channel.params || {};
    for (const key of ["interval", "period", "depth_levels"]) {
        const values = stringArray(params[key]);
        if (values.length > 0) return values;
        if (Array.isArray(params[key])) return params[key].map(String);
    }
    return [];
}

function capabilitySummary(exchange: ExchangeCapabilityPayload): string {
    const channels = exchange.channels || [];
    const labels = CHANNEL_ORDER
        .filter((channel) => channels.some((item) => item.channel === channel))
        .slice(0, 5)
        .map(channelLabel);
    const remaining = new Set(channels.map((channel) => channel.channel)).size - labels.length;
    return remaining > 0 ? `${labels.join(" · ")} · +${remaining}` : labels.join(" · ");
}

function ProductSurfaceRow({ exchange }: { exchange: ExchangeCapabilityPayload }) {
    const surfaces = exchangeProductSurfaces(exchange);
    const marketProducts = Object.values(exchange.support?.products?.markets || {});
    const strictBook = marketProducts.some((market) => market.order_book.strict_full_depth);
    const liveSnapshotBook = marketProducts.some((market) => (
        market.order_book.snapshot_mode === "live_snapshot"
    ));
    const observationalTrade = marketProducts.some((market) => (
        market.trade_flow.mode === "observational"
    ));
    const pollingTrade = marketProducts.some((market) => (
        market.trade_flow.delivery_mode === "polling_observational"
    ));
    const strictTrade = marketProducts.some((market) => (
        market.trade_flow.mode === "strict_repairable"
    ));
    const advancedByChannel = new Map<string, string>();
    for (const market of marketProducts) {
        for (const [channel, product] of Object.entries(
            market.advanced_market_data.channels,
        )) {
            if (product.supported) advancedByChannel.set(channel, product.delivery_mode || "");
        }
    }
    const advancedModes = [...advancedByChannel.values()];
    const advancedLive = advancedModes.filter((mode) => (
        mode === "live_snapshot"
        || mode === "live_observational"
        || mode === "derived_live"
    )).length;
    const advancedPolling = advancedModes.filter((mode) => (
        mode === "polling_snapshot"
        || mode === "polling_observational"
        || mode === "derived_polling"
    )).length;
    const advancedHistory = advancedModes.filter((mode) => mode === "history_only").length;
    const advancedDetail = advancedByChannel.size > 0
        ? t("settings.exchange.surface.advancedSummary", {
            count: advancedByChannel.size,
            live: advancedLive,
            polling: advancedPolling,
            history: advancedHistory,
        })
        : null;
    const entries = [
        ["chart", "settings.exchange.surface.chart", surfaces.chart ? t("settings.exchange.surface.ready") : null],
        ["advancedMarketData", "settings.exchange.surface.advanced", surfaces.advancedMarketData ? advancedDetail : null],
        ["orderBook", "settings.exchange.surface.orderBook", surfaces.orderBook
            ? t(strictBook
                ? "settings.exchange.surface.strictBook"
                : liveSnapshotBook
                    ? "settings.exchange.surface.liveSnapshotBook"
                    : "settings.exchange.surface.pollingSnapshotBook")
            : null],
        ["tradeFlow", "settings.exchange.surface.tradeFlow", surfaces.tradeFlow
            ? t(strictTrade
                ? "settings.exchange.surface.strictTrade"
                : pollingTrade
                    ? "settings.exchange.surface.pollingObservedTrade"
                : observationalTrade
                    ? "settings.exchange.surface.observedTrade"
                    : "settings.exchange.surface.ready")
            : null],
    ] as const;
    return (
        <dl className="st-ex-surfaces">
            {entries.map(([field, label, detail]) => (
                <div key={field} className="st-ex-surface" data-supported={surfaces[field] ? "true" : "false"}>
                    <dt>{t(label)}</dt>
                    <dd>{surfaces[field] ? detail : t("settings.exchange.surface.pending")}</dd>
                </div>
            ))}
        </dl>
    );
}

function MarketCapabilityDetail({
    exchange,
    market,
    connectionCheck,
    onTest,
}: {
    exchange: ExchangeCapabilityPayload;
    market: ExchangeMarketPayload;
    connectionCheck: ExchangeConnectionCheck | undefined;
    onTest(): void;
}) {
    const channels = exchangeChannelsForMarket(exchange, market.market_type)
        .sort((left, right) => {
            const leftIndex = CHANNEL_ORDER.indexOf(left.channel);
            const rightIndex = CHANNEL_ORDER.indexOf(right.channel);
            return (leftIndex < 0 ? 99 : leftIndex) - (rightIndex < 0 ? 99 : rightIndex);
        });

    return (
        <section className="st-ex-market">
            <div className="st-ex-market-head">
                <div>
                    <strong>{market.label || market.market_type}</strong>
                    <code>{market.market_type}</code>
                </div>
                <Button
                    size="sm"
                    onClick={onTest}
                    disabled={connectionCheck?.status === "running" || !exchangeIsRoutable(exchange)}
                >
                    {connectionCheck?.status === "running"
                        ? t("settings.exchange.testing")
                        : t("settings.exchange.testMarket")}
                </Button>
            </div>

            {connectionCheck?.status === "success" && (
                <InlineAlert tone="success">
                    {t("settings.exchange.testSuccess", { count: connectionCheck.symbolCount ?? 0 })}
                </InlineAlert>
            )}
            {connectionCheck?.status === "error" && (
                <InlineAlert tone="danger">{connectionCheck.error}</InlineAlert>
            )}

            {channels.length === 0 ? (
                <p className="st-ex-muted">{t("settings.exchange.noChannels")}</p>
            ) : (
                <Disclosure summary={t("settings.exchange.channels", { count: channels.length })}>
                    <table className="st-ex-channels">
                        <thead>
                            <tr>
                                <th scope="col">{t("settings.exchange.dataChannel")}</th>
                                <th scope="col">{t("settings.exchange.realtime")}</th>
                                <th scope="col">{t("settings.exchange.history")}</th>
                                <th scope="col">{t("settings.exchange.dataQuality")}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {channels.map((channel) => {
                                const values = configuredValues(channel);
                                const fields = stringArray(channel.available_fields);
                                const unavailableFields = stringArray(channel.unavailable_fields);
                                const limitations = stringArray(channel.known_limitations);
                                return (
                                    <tr key={channel.channel}>
                                        <th scope="row">
                                            {channelLabel(channel.channel)}
                                            {values.length > 0 && (
                                                <span className="st-ex-values">
                                                    {values.slice(0, 8).join(" · ")}{values.length > 8 ? ` · +${values.length - 8}` : ""}
                                                </span>
                                            )}
                                        </th>
                                        <td>{formatTransports(channel.realtime_transports, channel.realtime)}</td>
                                        <td>{formatTransports(channel.history_transports, channel.history)}</td>
                                        <td className="st-ex-quality">
                                            <strong>{qualityLabel(channel)}</strong>
                                            {fields.length > 0 && <span>{t("settings.exchange.fields")}: {fields.join(", ")}</span>}
                                            {unavailableFields.length > 0 && <span>{t("settings.exchange.unavailableFields")}: {unavailableFields.join(", ")}</span>}
                                            {limitations.map((limitation) => <span key={limitation}>{limitation}</span>)}
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </Disclosure>
            )}
        </section>
    );
}

export interface ExchangeSettingsPanelProps {
    currentExchange: string;
    supportedExchanges: ExchangeCapabilityPayload[];
    exchangeCatalogSummary: CcxtCatalogSummaryPayload | null;
    exchangeConnectionChecks: Record<string, ExchangeConnectionCheck>;
    exchangeListLoading: boolean;
    exchangeListError: string | null;
    onRefreshExchanges(): void;
    onTestExchangeMarket(exchange: string, marketType: string): void;
}

export default function ExchangeSettingsPanel({
    currentExchange,
    supportedExchanges,
    exchangeCatalogSummary,
    exchangeConnectionChecks,
    exchangeListLoading,
    exchangeListError,
    onRefreshExchanges,
    onTestExchangeMarket,
}: ExchangeSettingsPanelProps) {
    const locale = useLocale();
    const [search, setSearch] = useState("");
    const [filter, setFilter] = useState<ExchangeSupportFilter>("all");
    const [expandedExchange, setExpandedExchange] = useState(currentExchange);
    const filteredExchanges = useMemo(
        () => filterExchangeCapabilities(supportedExchanges, search, filter, currentExchange),
        [currentExchange, filter, search, supportedExchanges],
    );
    const routableCount = supportedExchanges.filter(exchangeIsRoutable).length;
    const streamCount = supportedExchanges.filter((exchange) => (
        (exchange.channels || []).some((channel) => (
            channel.channel === "kline"
            && channel.realtime === true
            && stringArray(channel.realtime_transports).includes("plugin_stream")
        ))
    )).length;

    const marketsLabel = (exchange: ExchangeCapabilityPayload) => (
        exchange.markets.length > 0
            ? new Intl.ListFormat(locale, { style: "narrow", type: "conjunction" }).format(exchange.markets.map((market) => market.label || market.market_type))
            : t("settings.exchange.noMarkets")
    );

    return (
        <div className="st-group st-ex">
            <div className="st-ex-head">
                <p className="st-group-desc">{t("settings.exchange.summary")}</p>
                <Button size="sm" onClick={onRefreshExchanges} disabled={exchangeListLoading}>
                    {exchangeListLoading ? t("settings.exchange.refreshing") : t("settings.exchange.refresh")}
                </Button>
            </div>

            {exchangeCatalogSummary && (
                <div className="st-ex-summary">
                    <Stat label={t("settings.exchange.routable")} value={routableCount} />
                    <Stat label={t("settings.exchange.wsKline")} value={streamCount} />
                    {/* Implementation figures stay available, folded away for the curious */}
                    <Disclosure summary={t("plugin.techDetails")} className="st-ex-tech">
                        <dl className="st-kv">
                            <dt>{t("settings.exchange.kernelVersion")}</dt>
                            <dd>CCXT {exchangeCatalogSummary.version}</dd>
                            <dt>{t("settings.exchange.adapterIds")}</dt>
                            <dd>{exchangeCatalogSummary.rest_exchange_ids}</dd>
                            <dt>{t("settings.exchange.proIds")}</dt>
                            <dd>{exchangeCatalogSummary.pro_exchange_ids}</dd>
                        </dl>
                    </Disclosure>
                </div>
            )}

            <div className="st-ex-toolbar">
                <Input
                    type="search"
                    aria-label={t("settings.exchange.search")}
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder={t("settings.exchange.searchPlaceholder")}
                />
                <SegmentedControl<ExchangeSupportFilter>
                    size="sm"
                    label={t("settings.exchange.filter")}
                    value={filter}
                    onChange={setFilter}
                    options={FILTERS.map((option) => ({ value: option.value, label: t(option.label) }))}
                />
            </div>

            {exchangeListError && (
                <InlineAlert tone="danger" title={t("settings.exchange.loadFailed")}>{exchangeListError}</InlineAlert>
            )}
            {!exchangeListError && exchangeListLoading && supportedExchanges.length === 0 && (
                <EmptyState compact title={t("settings.exchange.loading")} />
            )}
            {!exchangeListError && !exchangeListLoading && supportedExchanges.length === 0 && (
                <InlineAlert tone="warning">{t("settings.exchange.empty")}</InlineAlert>
            )}
            {supportedExchanges.length > 0 && filteredExchanges.length === 0 && (
                <EmptyState compact title={t("settings.exchange.noMatches")} />
            )}

            <ul className="st-ex-list">
                {filteredExchanges.map((exchange) => {
                    const isExpanded = expandedExchange === exchange.exchange;
                    const isCurrent = exchange.exchange === currentExchange;
                    const isRoutable = exchangeIsRoutable(exchange);
                    const provider = exchangeProvider(exchange);
                    const qualifications = exchange.support?.qualifications
                        || (exchange.support?.qualification ? [exchange.support.qualification] : []);
                    const meta = [
                        providerLabel(provider),
                        marketsLabel(exchange),
                        ...(exchangeIsPollingOnly(exchange) ? [t("settings.exchange.pollingOnly")] : []),
                    ];
                    return (
                        <li
                            key={exchange.exchange}
                            className="st-ex-item"
                            data-expanded={isExpanded ? "true" : undefined}
                            data-current={isCurrent ? "true" : undefined}
                            data-unroutable={isRoutable ? undefined : "true"}
                        >
                            <button
                                type="button"
                                className="st-ex-row"
                                onClick={() => setExpandedExchange(isExpanded ? "" : exchange.exchange)}
                                aria-expanded={isExpanded}
                            >
                                <span className="st-ex-chevron" aria-hidden="true"><Icon name="chevron-right" size={14} /></span>
                                <span className="st-ex-identity">
                                    <span className="st-ex-name">
                                        <strong>{exchange.name || exchange.exchange}</strong>
                                        <code>{exchange.exchange}</code>
                                    </span>
                                    <span className="st-ex-meta">{meta.join(" · ")}</span>
                                    <span className="st-ex-capabilities">{capabilitySummary(exchange) || t("settings.exchange.noChannels")}</span>
                                </span>
                                <span className="st-ex-badges">
                                    {isCurrent && <Badge tone="accent">{t("settings.exchange.current")}</Badge>}
                                    {!isRoutable && <Badge tone="danger">{t("settings.exchange.unroutable")}</Badge>}
                                </span>
                            </button>

                            {isExpanded && (
                                <div className="st-ex-detail">
                                    <section>
                                        <h4>{t("settings.exchange.productSurfaces")}</h4>
                                        <ProductSurfaceRow exchange={exchange} />
                                    </section>

                                    {exchange.markets.map((market) => (
                                        <MarketCapabilityDetail
                                            key={market.market_type}
                                            exchange={exchange}
                                            market={market}
                                            connectionCheck={exchangeConnectionChecks[
                                                exchangeMarketCheckKey(exchange.exchange, market.market_type)
                                            ]}
                                            onTest={() => onTestExchangeMarket(exchange.exchange, market.market_type)}
                                        />
                                    ))}

                                    {exchange.known_limitations.length > 0 && (
                                        <section>
                                            <h4>{t("settings.exchange.knownLimitations")}</h4>
                                            <ul className="st-plain-list">
                                                {exchange.known_limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
                                            </ul>
                                        </section>
                                    )}

                                    <Disclosure summary={t("plugin.techDetails")}>
                                        <dl className="st-kv">
                                            <dt>{t("settings.exchange.verificationTitle")}</dt>
                                            <dd>{isRoutable
                                                ? verificationLabel(exchange.support?.verification_level || "capability_contract")
                                                : t("settings.exchange.unroutable")}</dd>
                                            {exchangeHasDerivatives(exchange) && <>
                                                <dt>{t("settings.exchange.derivatives")}</dt>
                                                <dd>{t("settings.exchange.supported")}</dd>
                                            </>}
                                        </dl>
                                        {qualifications.map((qualification) => (
                                            <div key={qualification.evidence_id} className="st-ex-qualification">
                                                <strong>{verificationLabel(qualification.level)}</strong>
                                                <span>CCXT {qualification.ccxt_version}</span>
                                                <span>{qualification.market_types.join(" / ")}</span>
                                                <span>{qualification.channels.map(channelLabel).join(" · ")}</span>
                                                {qualification.event_count != null && (
                                                    <span>{t("settings.exchange.verification.events", { count: qualification.event_count })}</span>
                                                )}
                                                {qualification.duration_seconds != null && (
                                                    <span>{t("settings.exchange.verification.durationHours", {
                                                        hours: qualification.duration_seconds / 3600,
                                                    })}</span>
                                                )}
                                                <span>{new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(new Date(qualification.verified_at))}</span>
                                            </div>
                                        ))}
                                    </Disclosure>
                                </div>
                            )}
                        </li>
                    );
                })}
            </ul>
        </div>
    );
}
