import { memo } from "react";
import type { ReactNode } from "react";
import SymbolSearch from "../features/symbol-search/SymbolSearch.js";
import { markPerf } from "../runtime/performance/perfMarks";
import {
  loadReplayLauncherDialog,
  loadSettingsModal,
} from "./lazySurfaceLoaders.js";
import {
  buildMarketSummary,
  formatPrice,
} from "../features/market-data/marketDataView";
import type { MarketSummary } from "../features/market-data/klineContracts.js";
import type { MarketDisplayData } from "../features/market-data/marketDataView.js";
import type { SymbolSearchProps } from "../features/symbol-search/SymbolSearch.js";
import type { AdvancedMarketRuntimeView } from "../features/advanced-market-data/advancedMarketDataTypes.js";
import type { ReplayEntryCapabilityView } from "../features/replay/useReplayEntryCapability.js";
import { isBacktestEntryEnabled } from "../features/backtest/backtestFlags.js";
import { useAdvancedMarketSummary } from "../features/advanced-market-data/useAdvancedMarketSnapshots.js";
import { t } from "../i18n/index.js";
import { useLocale } from "../i18n/useLocale.js";
import MarketTopBarFrame from "./MarketTopBarFrame.js";
import { AlertRailIcon, CapabilityRailIcon, ProfileRailIcon } from "./marketRailIcons.js";

export interface TopBarSymbolSearchModel extends Omit<SymbolSearchProps, "onSelect"> {
  onSelectSymbol: SymbolSearchProps["onSelect"];
}

export interface TopBarControlsModel {
  onOpenSettings(): void;
  indicatorPanelOpen: boolean;
  onToggleIndicatorPanel(): void;
  alertPanelOpen: boolean;
  onToggleAlertPanel(): void;
  activeIndicatorCount: number;
}

export interface TopBarProps {
  symbolSearch: TopBarSymbolSearchModel;
  controls: TopBarControlsModel;
  marketSummary: Omit<MarketSummary, "displayData"> & {
    displayData: MarketDisplayData | null;
  };
  advancedMarketData: AdvancedMarketRuntimeView;
  replayEntry: ReplayEntryCapabilityView;
  onOpenReplayLauncher(): void;
  identityAccessory?: ReactNode;
  extensionControls?: ReactNode;
}

function TopBar({
  symbolSearch,
  controls,
  marketSummary,
  advancedMarketData,
  replayEntry,
  onOpenReplayLauncher,
  identityAccessory,
  extensionControls,
}: TopBarProps) {
  const {
    currentSymbol,
    currentMarketType,
    currentExchange,
    exchangeCatalog,
    onSelectSymbol,
    watchlists,
    onAddToWatchlist,
  } = symbolSearch;
  const {
    onOpenSettings,
    indicatorPanelOpen,
    onToggleIndicatorPanel,
    alertPanelOpen,
    onToggleAlertPanel,
    activeIndicatorCount,
  } = controls;
  const { displayData, isUp, priceChange } = buildMarketSummary(marketSummary.displayData);
  const advancedSummary = useAdvancedMarketSummary(advancedMarketData);
  const backtestEntryEnabled = isBacktestEntryEnabled();
  useLocale();
  const basisText = advancedSummary.basis == null
    ? "--"
    : `${advancedSummary.basis >= 0 ? "+" : "-"}${formatPrice(Math.abs(advancedSummary.basis))}`;

  const marketMetrics = (
    <div
      className={`advanced-market-summary advanced-market-summary-${advancedSummary.connectionStatus}`}
      aria-label={t("shell.derivativesSummary")}
    >
      <div className="advanced-market-chip" data-market-metric="mark-price">
        <span className="advanced-market-chip-label">{t("shell.mark")}</span>
        <span className="advanced-market-chip-value">{formatPrice(advancedSummary.markPrice)}</span>
      </div>
      <div className="advanced-market-chip" data-market-metric="index-price">
        <span className="advanced-market-chip-label">{t("shell.index")}</span>
        <span className="advanced-market-chip-value">{formatPrice(advancedSummary.indexPrice)}</span>
      </div>
      <div className="advanced-market-chip" data-market-metric="basis">
        <span className="advanced-market-chip-label">{t("shell.basis")}</span>
        <span className="advanced-market-chip-value">{basisText}</span>
        {advancedSummary.basisBps != null && (
          <span className="advanced-market-chip-suffix">
            {advancedSummary.basisBps >= 0 ? "+" : ""}{advancedSummary.basisBps.toFixed(2)} bps
          </span>
        )}
      </div>
    </div>
  );

  return (
    <MarketTopBarFrame
      source="live"
      navigation={<>
        {replayEntry.state === "enabled" && (
        <button
          className="replay-entry-link"
          data-replay-entry="enabled"
          type="button"
          onPointerEnter={loadReplayLauncherDialog}
          onMouseEnter={loadReplayLauncherDialog}
          onFocus={loadReplayLauncherDialog}
          onClick={onOpenReplayLauncher}
        >
          {t("shell.replay")}
        </button>
        )}
        {(replayEntry.state === "checking" || replayEntry.state === "disabled") && (
        <button
          className="replay-entry-link replay-entry-disabled"
          data-replay-entry={replayEntry.state}
          type="button"
          disabled
          title={replayEntry.reason}
        >
          {t("shell.replay")}
        </button>
        )}
        {backtestEntryEnabled && (
        <a
          className="replay-entry-link backtest-entry-link"
          data-backtest-entry="enabled"
          data-strategy-entry="enabled"
          title={t("shell.strategyHint")}
          href="/strategy.html"
          target="_blank"
          rel="noreferrer"
        >
          {t("shell.strategy")}
        </a>
        )}
      </>}
      identity={<>
        <SymbolSearch
          currentSymbol={currentSymbol}
          onSelect={onSelectSymbol}
          {...(currentMarketType === undefined ? {} : { currentMarketType })}
          {...(currentExchange === undefined ? {} : { currentExchange })}
          {...(exchangeCatalog === undefined ? {} : { exchangeCatalog })}
          {...(watchlists === undefined ? {} : { watchlists })}
          {...(onAddToWatchlist === undefined ? {} : { onAddToWatchlist })}
        />
        {identityAccessory}
      </>}
      controls={<>
        <button
        className="settings-btn indicator-toggle-btn"
        title={t("shell.settings")}
        aria-label={t("shell.settings")}
        onPointerEnter={loadSettingsModal}
        onMouseOver={loadSettingsModal}
        onMouseEnter={loadSettingsModal}
        onFocus={loadSettingsModal}
        onClick={() => {
          markPerf("lazy.settings.open.start", { trigger: "button" });
          onOpenSettings();
        }}
      >
        <span aria-hidden="true" style={{ display: "flex" }}><CapabilityRailIcon /></span>
        </button>

        <button
        className={`indicator-toggle-btn ${indicatorPanelOpen ? "active" : ""}`}
        onClick={onToggleIndicatorPanel}
        title={t("shell.indicators")}
        aria-label={`${t("shell.indicators")} ${activeIndicatorCount}`}
        aria-expanded={indicatorPanelOpen}
      >
        <span aria-hidden="true" style={{ display: "flex" }}><ProfileRailIcon /></span>
        {activeIndicatorCount > 0 && (
          <span className="indicator-badge">{activeIndicatorCount}</span>
        )}
        </button>

        <button
        className={`indicator-toggle-btn alert-toggle-btn ${alertPanelOpen ? "active" : ""}`}
        onClick={onToggleAlertPanel}
        title={t("shell.alerts")}
        aria-label={t("shell.alerts")}
        aria-expanded={alertPanelOpen}
      >
        <span aria-hidden="true" style={{ display: "flex" }}><AlertRailIcon /></span>
        </button>
        {extensionControls}
      </>}
      quote={displayData && (
        <div className="price-info">
          <span className={`current-price ${isUp ? "price-up" : "price-down"}`}>
            {formatPrice(displayData.close)}
          </span>
          <span className={`price-change ${isUp ? "change-positive" : "change-negative"}`}>
            {isUp ? "▲" : "▼"} {Math.abs(priceChange).toFixed(2)}%
          </span>
        </div>
      )}
      marketMetrics={advancedMarketData.summaryEnabled && (
        <>
          <div className="live-market-metrics-inline">{marketMetrics}</div>
          <details
            className="live-market-metrics-compact"
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.currentTarget.open = false;
                event.stopPropagation();
              }
            }}
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.open = false;
            }}
          >
            <summary>{t("shell.derivativesSummary")}</summary>
            {marketMetrics}
          </details>
        </>
      )}
    />
  );
}

export default memo(TopBar);
