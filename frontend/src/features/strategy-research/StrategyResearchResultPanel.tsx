import { useState } from "react";
import { t } from "../../i18n/index.js";
import {
  ChartStrategyResultContextBar,
  ChartStrategyResultOverview,
  ChartStrategyTradeList,
  TradeExplanationPopover,
  type TradeExplanationSelection,
} from "../backtest/chart-tester/ChartStrategyResultViews.js";
import type { ChartStrategyResultBundle } from "../backtest/chart-tester/chartStrategyResultCache.js";
import type { ChartStrategyTesterStaleReason } from "../backtest/chart-tester/chartStrategyTesterState.js";
import { useLocale } from "../../i18n/useLocale.js";
import type { StrategyResearchNetworkDiagnostics } from "./strategyResearchHostHealth.js";
import type { ChartContextResolution } from "../backtest/backtestApi.js";

export function StrategyResearchResultPanel({
  result,
  stale,
  staleReasons,
  barOnly,
  error,
  runStatus,
  network,
  onOpenAdvanced,
  onLocateTrade,
  dataResolution,
}: {
  result: ChartStrategyResultBundle | null;
  stale: boolean;
  staleReasons: readonly ChartStrategyTesterStaleReason[];
  barOnly: boolean;
  error: string | null;
  runStatus: string;
  network: StrategyResearchNetworkDiagnostics | null;
  onOpenAdvanced?(): void;
  onLocateTrade?(timeMs: number): void;
  dataResolution?: ChartContextResolution | null;
}) {
  const locale = useLocale();
  const [activeTab, setActiveTab] = useState<"overview" | "trades">("overview");
  const [explanation, setExplanation] = useState<TradeExplanationSelection | null>(null);
  if (error !== null) {
    return <p className="strategy-research-error" role="alert">{error}</p>;
  }
  if (result === null) {
    return (
      <section data-testid="strategy-research-result-panel" data-run-status={runStatus}>
        <h3>{t("strategy.resultSlot")}</h3>
        <p role="status">{t(runStatus === "NEEDS_DATA"
          ? "chartTester.status.needs_data"
          : runStatus === "RUNNING" || runStatus === "QUEUED" || runStatus === "RESOLVING"
            ? "chartTester.overview.pendingDetail"
            : "chartTester.placeholder.trades")}</p>
        {runStatus === "NEEDS_DATA" && dataResolution && <>
          <p>{t("chartTester.status.needsDataDetail", { bars: dataResolution.materialize.estimated_bars ?? t("chartTester.unknown") })}</p>
          <p>{t("chartTester.settings.dateAbsolute", {
            start: dataResolution.coverage.requested_start_ms === null ? t("chartTester.unknown") : new Date(dataResolution.coverage.requested_start_ms).toLocaleString(locale),
            end: dataResolution.coverage.requested_end_ms === null ? t("chartTester.unknown") : new Date(dataResolution.coverage.requested_end_ms).toLocaleString(locale),
          })}</p>
        </>}
        {barOnly ? (
          <p data-testid="strategy-research-bar-only-result">{t("chartTester.result.fidelityFast")}</p>
        ) : null}
        {network !== null ? (
          <details data-testid="strategy-research-network-guard"><summary>{t("strategy.network.summary")}</summary><p>
            {network.installed ? t("strategy.network.installed") : t("strategy.network.missing")}
          </p></details>
        ) : null}
      </section>
    );
  }
  return (
    <section
      className="strategy-research-result-panel"
      data-testid="strategy-research-result-panel"
      data-stale={stale ? "true" : "false"}
      data-stale-reasons={staleReasons.join(",")}
      data-fidelity={barOnly ? "BAR_APPROX" : result.run.fidelity_mode}
    >
      <ChartStrategyResultContextBar
        result={result}
        locale={locale}
        stale={stale}
      />
      {barOnly ? (
        <p data-testid="strategy-research-no-precise">{t("chartTester.result.fidelityFast")}</p>
      ) : null}
      <div className="strategy-research-result-tabs" role="tablist" aria-label={t("strategy.resultSlot")}>
        {(["overview", "trades"] as const).map((tab) => (
          <button key={tab} type="button" role="tab" aria-selected={activeTab === tab}
            onClick={() => setActiveTab(tab)}>{t(tab === "overview" ? "chartTester.tab.overview" : "chartTester.tab.trades")}</button>
        ))}
      </div>
      <div role="tabpanel" aria-label={t(activeTab === "overview" ? "chartTester.tab.overview" : "chartTester.tab.trades")}>
      {activeTab === "overview" ? <ChartStrategyResultOverview
        result={result}
        stale={stale}
        onOpenTrades={() => setActiveTab("trades")}
        {...(onOpenAdvanced ? { onOpenAdvanced } : {})}
      /> : <ChartStrategyTradeList
        result={result}
        locale={locale}
        onLocateTrade={(timeMs) => { if (!stale) onLocateTrade?.(timeMs); }}
        onSelectExplanation={setExplanation}
      />}
      </div>
      {explanation && <TradeExplanationPopover selection={explanation} onClose={() => setExplanation(null)} />}
      {network !== null ? (
        <details className="strategy-research-network-guard" data-testid="strategy-research-network-guard">
          <summary>{t("strategy.network.summary")}</summary>
          <p>{network.installed ? t("strategy.network.installed") : t("strategy.network.missing")}</p>
          <p>{t("strategy.network.policy", { policy: network.policy })}</p>
          <p>{t("strategy.network.blocked", { count: network.blockedAttempts })}</p>
        </details>
      ) : null}
    </section>
  );
}
