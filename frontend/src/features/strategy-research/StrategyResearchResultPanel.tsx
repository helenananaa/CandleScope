import { useState } from "react";
import { Badge, Button, Disclosure, InlineAlert, TabPanel, Tabs } from "../../components/ui/index.js";
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
  onOpenReplay,
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
  onOpenReplay?(): void;
  onLocateTrade?(timeMs: number): void;
  dataResolution?: ChartContextResolution | null;
}) {
  const locale = useLocale();
  const [activeTab, setActiveTab] = useState<"overview" | "trades">("overview");
  const [explanation, setExplanation] = useState<TradeExplanationSelection | null>(null);
  if (error !== null) {
    return <InlineAlert tone="danger">{error}</InlineAlert>;
  }
  const networkGuard = network !== null ? (
    <Disclosure className="strategy-research-network-guard" summary={t("strategy.network.summary")}>
      <div data-testid="strategy-research-network-guard">
        <p>{network.installed ? t("strategy.network.installed") : t("strategy.network.missing")}</p>
        {result !== null && <>
          <p>{t("strategy.network.policy", { policy: network.policy })}</p>
          <p>{t("strategy.network.blocked", { count: network.blockedAttempts })}</p>
        </>}
      </div>
    </Disclosure>
  ) : null;
  if (result === null) {
    return (
      <section className="strategy-research-result-empty" data-testid="strategy-research-result-panel" data-run-status={runStatus}>
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
          <Badge className="strategy-research-fidelity">
            <span data-testid="strategy-research-bar-only-result">{t("chartTester.result.fidelityFast")}</span>
          </Badge>
        ) : null}
        {networkGuard}
      </section>
    );
  }
  const external = result.report.strategy?.external_provider;
  const tabsId = "strategy-research-result";
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
      <div className="strategy-research-result-bar">
        <Tabs
          id={tabsId}
          label={t("strategy.resultSlot")}
          value={activeTab}
          onChange={setActiveTab}
          tabs={[
            { value: "overview", label: t("chartTester.tab.overview") },
            { value: "trades", label: t("chartTester.tab.trades") },
          ]}
        />
        <span className="strategy-research-result-meta">
          {barOnly ? (
            <Badge><span data-testid="strategy-research-no-precise">{t("chartTester.result.fidelityFast")}</span></Badge>
          ) : null}
          {external && <Badge tone="accent">
            <span data-testid="strategy-research-external-result">{t("research.external.model")} · {external.provider_id} · {external.provider_revision}</span>
          </Badge>}
          {onOpenReplay && <Button size="sm" onClick={onOpenReplay}>{t("report.replay")}</Button>}
        </span>
      </div>
      <TabPanel tabsId={tabsId} value={activeTab} className="strategy-research-result-body">
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
      </TabPanel>
      {explanation && <TradeExplanationPopover selection={explanation} onClose={() => setExplanation(null)} />}
      {networkGuard}
    </section>
  );
}
