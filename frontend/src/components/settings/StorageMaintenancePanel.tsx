import { Button } from "../ui/Button.js";
import { Badge, Disclosure, InlineAlert } from "../ui/Display.js";
import type { ReactNode } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import type {
    MaintenanceResult,
    MaintenanceScope,
} from "../../features/settings/maintenanceSettingsRuntime.js";

function resultTone(status: string | undefined): "success" | "warning" | "danger" {
    if (status === 'ok') return 'success';
    if (status === 'partial' || status === 'warning' || status === 'empty') return 'warning';
    return 'danger';
}

function getRepairStatusLabel(status: string | undefined): string {
    if (status === 'repaired') return t("settings.maint.repaired");
    if (status === 'failed') return t("settings.maint.failed");
    return t("settings.maint.passed");
}

function renderRepairDetails(result: MaintenanceResult): ReactNode {
    if (!Array.isArray(result.results) || result.results.length === 0) return null;
    return (
        <div className="st-series-list">
            {result.results.slice(0, 6).map((item) => (
                <div key={`${item.symbol}-${item.interval}`} className="st-series-item">
                    <div className="st-series-line">
                        <span className="st-series-name">{item.symbol} · {item.interval}</span>
                        <Badge tone={item.status === 'repaired' ? 'success' : item.status === 'failed' ? 'danger' : 'neutral'}>
                            {getRepairStatusLabel(item.status)}
                        </Badge>
                    </div>
                    <div className="st-series-msg">{item.message}</div>
                </div>
            ))}
            {result.results.length > 6 && (
                <div className="st-series-more">
                    {t("settings.maint.omitted", { count: result.results.length - 6 })}
                </div>
            )}
        </div>
    );
}

function renderGapScanDetails(result: MaintenanceResult): ReactNode {
    if (!Array.isArray(result.results) || result.results.length === 0) return null;
    return (
        <div className="st-series-list">
            {result.results.map((item, index) => (
                <div key={`${item.exchange}-${item.market_type}-${item.symbol}-${item.interval}-${item.lane}-${index}`} className="st-series-item">
                    <div className="st-series-line">
                        <span className="st-series-name">
                            {item.symbol} · {item.interval}
                        </span>
                        <Badge tone={item.status === 'filled' ? 'success' : item.status === 'ok' ? 'neutral' : 'danger'}>
                            {item.status === 'filled' ? t("settings.maint.filled") : item.status === 'ok' ? t("settings.maint.passed") : t("settings.maint.failed")}
                        </Badge>
                    </div>
                    <div className="st-series-msg">{item.message}</div>
                    <div className="st-series-msg">{t("settings.maint.inspectedRange", {
                        from: auditTime(item.scanned_from_ms), to: auditTime(item.scanned_to_ms),
                    })}</div>
                    <div className="st-series-msg">{t("settings.maint.remainingGaps", {
                        count: item.remaining_gaps ?? t("strategyCompare.unknown"),
                    })}</div>
                    {(item.truncated || item.status === 'unscanned') && (
                        <div className="st-series-msg">{t("settings.maint.continueFrom", { time: auditTime(item.next_cursor_ms) })}</div>
                    )}
                    {item.repair_errors?.map((error, errorIndex) => <div key={errorIndex} className="st-series-msg">{error}</div>)}
                </div>
            ))}
        </div>
    );
}

function auditTime(value: number | null | undefined): string {
    if (value == null || !Number.isFinite(value)) return t("strategyCompare.unknown");
    return new Date(value).toISOString().replace('T', ' ').replace('.000Z', '');
}

function exchangeLabel(exchange: string | null | undefined): string {
    return String(exchange || '').charAt(0).toUpperCase() + String(exchange || '').slice(1);
}

export interface StorageMaintenancePanelProps {
    currentSymbol: string;
    currentMarketType: string;
    currentExchange: string;
    currentScopeSymbols: string[];
    watchlistScopeSymbols: string[];
    storageRepairLoading: boolean;
    storageRepairResult: MaintenanceResult | null;
    gapScanLoading: boolean;
    gapScanResult: MaintenanceResult | null;
    maintenanceScope: MaintenanceScope | null;
    exchangeRefreshLoading: boolean;
    exchangeRefreshResult: MaintenanceResult | null;
    onStorageRepair(scope: MaintenanceScope): void;
    onGapScan(scope: MaintenanceScope): void;
    onExchangeRefresh(): void;
}

export default function StorageMaintenancePanel({
    currentSymbol,
    currentMarketType,
    currentExchange,
    currentScopeSymbols,
    watchlistScopeSymbols,
    storageRepairLoading,
    storageRepairResult,
    gapScanLoading,
    gapScanResult,
    maintenanceScope,
    exchangeRefreshLoading,
    exchangeRefreshResult,
    onStorageRepair,
    onGapScan,
    onExchangeRefresh,
}: StorageMaintenancePanelProps) {
    useLocale();
    const scopeLabel = maintenanceScope === 'watchlist' ? t("settings.maint.scopeWatchlist") : t("settings.maint.scopeCurrent");

    const scopeLine = (result: MaintenanceResult) => [
        t("settings.maint.scopeLine", {
            scope: scopeLabel,
            exchange: exchangeLabel(result.exchange || currentExchange),
            market: result.market_type || currentMarketType,
        }),
        Array.isArray(result.symbols_filter) && result.symbols_filter.length > 0
            ? t("settings.maint.symbolCount", { count: result.symbols_filter.length })
            : '',
    ].join('');
    const busy = storageRepairLoading || gapScanLoading;

    return (
        <div className="st-group">
            <div className="st-group-desc">{t("settings.maint.desc")}</div>
            <ul className="st-launch-list">
                <li className="st-launch-row">
                    <div className="st-launch-text">
                        <strong>{t("settings.maint.repairName")}</strong>
                        <span>{t("settings.maint.repairDesc")}</span>
                    </div>
                    <div className="st-launch-actions">
                        <Button size="sm"
                            onClick={() => onStorageRepair('current')}
                            disabled={busy || currentScopeSymbols.length === 0}
                        >
                            {storageRepairLoading && maintenanceScope === 'current'
                                ? t("settings.maint.checking")
                                : t("settings.maint.currentChart", { symbol: currentSymbol || '-' })}
                        </Button>
                        <Button size="sm"
                            onClick={() => onStorageRepair('watchlist')}
                            disabled={busy || watchlistScopeSymbols.length === 0}
                        >
                            {storageRepairLoading && maintenanceScope === 'watchlist'
                                ? t("settings.maint.checking")
                                : t("settings.maint.watchlistCurrent", { count: watchlistScopeSymbols.length })}
                        </Button>
                    </div>
                    {storageRepairResult && (
                        <div className="st-launch-result">
                            <InlineAlert tone={resultTone(storageRepairResult.status)} title={storageRepairResult.message}>
                                {scopeLine(storageRepairResult)}
                                <div className="st-result-stats">
                                    <span>{t("settings.maint.checked", { count: storageRepairResult.checked_series || 0 })}</span>
                                    <span>{t("settings.maint.repairedCount", { count: storageRepairResult.repaired_series || 0 })}</span>
                                    <span>{t("settings.maint.passedCount", { count: storageRepairResult.unchanged_series || 0 })}</span>
                                    <span>{t("settings.maint.failedCount", { count: storageRepairResult.failed_series || 0 })}</span>
                                    <span>{t("settings.maint.deletedRows", { count: storageRepairResult.total_deleted_rows || 0 })}</span>
                                    <span>{t("settings.maint.writtenRows", { count: storageRepairResult.total_written_rows || 0 })}</span>
                                </div>
                            </InlineAlert>
                            {Array.isArray(storageRepairResult.results) && storageRepairResult.results.length > 0 && (
                                <Disclosure summary={t("settings.maint.details")}>{renderRepairDetails(storageRepairResult)}</Disclosure>
                            )}
                        </div>
                    )}
                </li>

                <li className="st-launch-row">
                    <div className="st-launch-text">
                        <strong>{t("settings.maint.gapName")}</strong>
                        <span>{t("settings.maint.gapDesc", { exchange: exchangeLabel(currentExchange) })}</span>
                    </div>
                    <div className="st-launch-actions">
                        <Button size="sm"
                            onClick={() => onGapScan('current')}
                            disabled={busy || currentScopeSymbols.length === 0}
                        >
                            {gapScanLoading && maintenanceScope === 'current'
                                ? t("settings.maint.scanning")
                                : gapScanResult?.has_more && maintenanceScope === 'current'
                                ? t("settings.maint.continueScan")
                                : t("settings.maint.currentChart", { symbol: currentSymbol || '-' })}
                        </Button>
                        <Button size="sm"
                            onClick={() => onGapScan('watchlist')}
                            disabled={busy || watchlistScopeSymbols.length === 0}
                        >
                            {gapScanLoading && maintenanceScope === 'watchlist'
                                ? t("settings.maint.scanning")
                                : gapScanResult?.has_more && maintenanceScope === 'watchlist'
                                ? t("settings.maint.continueScan")
                                : t("settings.maint.watchlistCurrent", { count: watchlistScopeSymbols.length })}
                        </Button>
                    </div>
                    {gapScanResult && (
                        <div className="st-launch-result">
                            <InlineAlert tone={resultTone(gapScanResult.status)} title={gapScanResult.message}>
                                {scopeLine(gapScanResult)}
                                <div className="st-result-stats">
                                    <span>{t("settings.maint.checked", { count: gapScanResult.scanned_ranges || 0 })}</span>
                                    <span>{t("settings.maint.passedCount", { count: gapScanResult.verified_ranges || 0 })}</span>
                                    <span>{t("settings.maint.failedCount", { count: gapScanResult.failed_ranges || 0 })}</span>
                                    <span>{t("settings.maint.elapsed", { seconds: ((gapScanResult.elapsed_ms || 0) / 1000).toFixed(1) })}</span>
                                </div>
                                {gapScanResult.errors?.map((error, index) => <div key={index} className="st-series-msg">{error}</div>)}
                            </InlineAlert>
                            {Array.isArray(gapScanResult.results) && gapScanResult.results.length > 0 && (
                                <Disclosure summary={t("settings.maint.details")}>{renderGapScanDetails(gapScanResult)}</Disclosure>
                            )}
                        </div>
                    )}
                </li>

                <li className="st-launch-row">
                    <div className="st-launch-text">
                        <strong>{t("settings.maint.refreshName")}</strong>
                        <span>{t("settings.maint.refreshDesc")}</span>
                    </div>
                    <div className="st-launch-actions">
                        <Button size="sm" onClick={onExchangeRefresh} disabled={exchangeRefreshLoading}>
                            {exchangeRefreshLoading ? t("settings.maint.refreshingPairs") : t("settings.maint.refreshBtn")}
                        </Button>
                    </div>
                    {exchangeRefreshResult && (
                        <div className="st-launch-result">
                            <InlineAlert tone={resultTone(exchangeRefreshResult.status)}>{exchangeRefreshResult.message}</InlineAlert>
                        </div>
                    )}
                </li>
            </ul>
        </div>
    );
}
