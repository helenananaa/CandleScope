import { Button } from "../ui/Button.js";
import type { ReactNode } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { Icon } from "../icons/Icon.js";
import type {
    MaintenanceResult,
    MaintenanceScope,
} from "../../features/settings/maintenanceSettingsRuntime.js";

function getRepairResultClassName(status: string | undefined): string {
    if (status === 'ok') return 'st-result-ok';
    if (status === 'partial' || status === 'warning' || status === 'empty') return 'st-result-warn';
    return 'st-result-fail';
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
                        <span className={`st-series-badge st-badge-${item.status === 'repaired' ? 'ok' : item.status === 'failed' ? 'fail' : 'info'}`}>
                            {getRepairStatusLabel(item.status)}
                        </span>
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
                        <span className={`st-series-badge st-badge-${item.status === 'filled' ? 'ok' : item.status === 'ok' ? 'info' : 'fail'}`}>
                            {item.status === 'ok' || item.status === 'filled' ? <Icon name="check" size={12} /> : '!'}
                        </span>
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

    return (
        <div className="st-group">
            <div className="st-group-title">{t("settings.maint.title")}</div>
            <div className="st-group-desc">{t("settings.maint.desc")}</div>

            <div className="st-tool-card">
                <div className="st-tool-header">
                    <span className="st-tool-icon"><Icon name="wrench" size={20} /></span>
                    <div>
                        <div className="st-tool-name">{t("settings.maint.repairName")}</div>
                        <div className="st-tool-desc">
                            {t("settings.maint.repairDesc")}
                        </div>
                    </div>
                </div>
                <div className="st-actions-row">
                    <Button variant="danger"
                        onClick={() => onStorageRepair('current')}
                        disabled={storageRepairLoading || gapScanLoading || currentScopeSymbols.length === 0}
                        style={{ flex: 1 }}
                    >
                        {storageRepairLoading && maintenanceScope === 'current'
                            ? t("settings.maint.checking")
                            : t("settings.maint.currentChart", { symbol: currentSymbol || '-' })}
                    </Button>
                    <Button
                        onClick={() => onStorageRepair('watchlist')}
                        disabled={storageRepairLoading || gapScanLoading || watchlistScopeSymbols.length === 0}
                        style={{ flex: 1 }}
                    >
                        {storageRepairLoading && maintenanceScope === 'watchlist'
                            ? t("settings.maint.checking")
                            : t("settings.maint.watchlistCurrent", { count: watchlistScopeSymbols.length })}
                    </Button>
                </div>
            </div>

            {storageRepairResult && (
                <div className={`st-result ${getRepairResultClassName(storageRepairResult.status)}`}>
                    <div className="st-result-head">{storageRepairResult.message}</div>
                    <div className="st-result-detail">
                        {t("settings.maint.scopeLine", {
                            scope: scopeLabel,
                            exchange: exchangeLabel(storageRepairResult.exchange || currentExchange),
                            market: storageRepairResult.market_type || currentMarketType,
                        })}
                        {Array.isArray(storageRepairResult.symbols_filter) && storageRepairResult.symbols_filter.length > 0
                            ? t("settings.maint.symbolCount", { count: storageRepairResult.symbols_filter.length })
                            : ''}
                    </div>
                    <div className="st-result-stats">
                        <span>{t("settings.maint.checked", { count: storageRepairResult.checked_series || 0 })}</span>
                        <span>{t("settings.maint.repairedCount", { count: storageRepairResult.repaired_series || 0 })}</span>
                        <span>{t("settings.maint.passedCount", { count: storageRepairResult.unchanged_series || 0 })}</span>
                        <span>{t("settings.maint.failedCount", { count: storageRepairResult.failed_series || 0 })}</span>
                        <span>{t("settings.maint.deletedRows", { count: storageRepairResult.total_deleted_rows || 0 })}</span>
                        <span>{t("settings.maint.writtenRows", { count: storageRepairResult.total_written_rows || 0 })}</span>
                    </div>
                    {renderRepairDetails(storageRepairResult)}
                </div>
            )}

            <div className="st-tool-card" style={{ marginTop: 12 }}>
                <div className="st-tool-header">
                    <span className="st-tool-icon"><Icon name="search" size={20} /></span>
                    <div>
                        <div className="st-tool-name">{t("settings.maint.gapName")}</div>
                        <div className="st-tool-desc">
                            {t("settings.maint.gapDesc", { exchange: exchangeLabel(currentExchange) })}
                        </div>
                    </div>
                </div>
                <div className="st-actions-row">
                    <Button
                        onClick={() => onGapScan('current')}
                        disabled={gapScanLoading || storageRepairLoading || currentScopeSymbols.length === 0}
                        style={{ flex: 1 }}
                    >
                        {gapScanLoading && maintenanceScope === 'current'
                            ? t("settings.maint.scanning")
                            : gapScanResult?.has_more && maintenanceScope === 'current'
                            ? t("settings.maint.continueScan")
                            : t("settings.maint.currentChart", { symbol: currentSymbol || '-' })}
                    </Button>
                    <Button
                        onClick={() => onGapScan('watchlist')}
                        disabled={gapScanLoading || storageRepairLoading || watchlistScopeSymbols.length === 0}
                        style={{ flex: 1 }}
                    >
                        {gapScanLoading && maintenanceScope === 'watchlist'
                            ? t("settings.maint.scanning")
                            : gapScanResult?.has_more && maintenanceScope === 'watchlist'
                            ? t("settings.maint.continueScan")
                            : t("settings.maint.watchlistCurrent", { count: watchlistScopeSymbols.length })}
                    </Button>
                </div>
            </div>

            {gapScanResult && (
                <div className={`st-result ${getRepairResultClassName(gapScanResult.status)}`}>
                    <div className="st-result-head">{gapScanResult.message}</div>
                    <div className="st-result-detail">
                        {t("settings.maint.scopeLine", {
                            scope: scopeLabel,
                            exchange: exchangeLabel(gapScanResult.exchange || currentExchange),
                            market: gapScanResult.market_type || currentMarketType,
                        })}
                        {Array.isArray(gapScanResult.symbols_filter) && gapScanResult.symbols_filter.length > 0
                            ? t("settings.maint.symbolCount", { count: gapScanResult.symbols_filter.length })
                            : ''}
                    </div>
                    <div className="st-result-stats">
                        <span>{t("settings.maint.checked", { count: gapScanResult.scanned_ranges || 0 })}</span>
                        <span>{t("settings.maint.passedCount", { count: gapScanResult.verified_ranges || 0 })}</span>
                        <span>{t("settings.maint.failedCount", { count: gapScanResult.failed_ranges || 0 })}</span>
                        <span>{t("settings.maint.elapsed", { seconds: ((gapScanResult.elapsed_ms || 0) / 1000).toFixed(1) })}</span>
                    </div>
                    {gapScanResult.errors?.map((error, index) => <div key={index} className="st-series-msg">{error}</div>)}
                    {renderGapScanDetails(gapScanResult)}
                </div>
            )}

            <div className="st-tool-card" style={{ marginTop: 12 }}>
                <div className="st-tool-header">
                    <span className="st-tool-icon"><Icon name="refresh" size={20} /></span>
                    <div>
                        <div className="st-tool-name">{t("settings.maint.refreshName")}</div>
                        <div className="st-tool-desc">
                            {t("settings.maint.refreshDesc")}
                        </div>
                    </div>
                </div>
                <Button
                    onClick={onExchangeRefresh}
                    disabled={exchangeRefreshLoading}
                    style={{ width: '100%' }}
                >
                    {exchangeRefreshLoading ? t("settings.maint.refreshingPairs") : t("settings.maint.refreshBtn")}
                </Button>
            </div>

            {exchangeRefreshResult && (
                <div className={`st-result ${getRepairResultClassName(exchangeRefreshResult.status)}`}>
                    <div className="st-result-head">{exchangeRefreshResult.message}</div>
                </div>
            )}
        </div>
    );
}
