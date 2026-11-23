import { useId, useState } from "react";
import { Button, Disclosure, InlineAlert, Stat, TabPanel, Tabs } from "../../../components/ui/index.js";
import { t, type MessageKey } from "../../../i18n/index.js";
import type { BacktestResearchRuntime } from "./backtestResearchTypes.js";
import { useLocale } from "../../../i18n/useLocale.js";
import { chartStrategyWinRate, formatChartStrategyNumber } from "../chart-tester/chartStrategyResultModel.js";
import BacktestRejections from "../BacktestRejections.js";
import ResearchPanelFrame from "./ResearchPanelFrame.js";
import { externalReportIsStale, isExternalRevision } from "./externalProviderModel.js";

type ResultTab = "SUMMARY" | "TRADES" | "TRACE" | "COMPARE" | "QUALITY";
const RESULT_TABS: ReadonlyArray<{ value: ResultTab; label: MessageKey }> = [
  { value: "SUMMARY", label: "research.results.tab.summary" },
  { value: "TRADES", label: "research.results.tab.trades" },
  { value: "TRACE", label: "research.results.tab.trace" },
  { value: "COMPARE", label: "research.results.tab.compare" },
  { value: "QUALITY", label: "research.results.tab.quality" },
];

export default function ResearchResultsPanel({ runtime }: { runtime: BacktestResearchRuntime }) {
  const locale = useLocale();
  const { advancedEnabled, report, activeRun, chart, runComparison, signalTrace, busy } = runtime.view;
  const [tab, setTab] = useState<ResultTab>("SUMMARY");
  const tabsId = useId();
  const external = report?.strategy?.external_provider;
  const staleExternal = externalReportIsStale({ report, run: activeRun,
    revisionId: runtime.view.selectedRevisionId, datasetId: runtime.view.selectedDatasetId,
    snapshot: runtime.view.snapshot, draftText: runtime.view.runDraftText,
    request: runtime.view.selectedRunRequest,
    externalSelected: isExternalRevision(runtime.view.revisions?.find((item) => item.revision_id === runtime.view.selectedRevisionId)) });
  return (
    <ResearchPanelFrame eyebrow={t("research.panel.results")} title={report?.report_label ?? ""} className="research-results-panel">
      {report ? (
        <>
          {external && <p className="research-panel-copy">{t("research.external.model")}: {external.provider_id} · {external.provider_revision}</p>}
          {staleExternal && <InlineAlert tone="warning">{t("research.external.staleReport")}</InlineAlert>}
          <div className="research-result-metrics">
            <Stat label={t("chartTester.result.realizedPnl")} value={formatChartStrategyNumber(report.metrics.realized_net_pnl)}
              tone={Number(report.metrics.realized_net_pnl) > 0 ? "success" : Number(report.metrics.realized_net_pnl) < 0 ? "danger" : "neutral"} />
            <Stat label={t("research.results.trades")} value={report.metrics.trade_count} />
            <Stat label={t("research.results.winRate")} value={Number(report.metrics.trade_count) === 0 ? "—" : chartStrategyWinRate(report.metrics.win_rate, locale)} />
            <Stat label={t("research.results.fidelity")} value={activeRun?.fidelity_mode ?? report.fidelity_mode} />
          </div>
          <BacktestRejections report={report} />
          {report.metrics.trade_count === 0 && <p className="research-panel-copy">{t(report.metrics.rejected_order_count
            ? "chartTester.result.rejectedNoTrades" : "chartTester.result.zeroTradesDetail")}</p>}
          {advancedEnabled && (
            <>
              <Tabs
                id={tabsId}
                label={t("research.aria.resultDetails")}
                value={tab}
                tabs={RESULT_TABS.map((item) => ({ value: item.value, label: t(item.label) }))}
                onChange={setTab}
              />
              <TabPanel tabsId={tabsId} value={tab} className="research-result-detail">
                <div data-result-tab={tab}>
                  {tab === "SUMMARY" && <Disclosure summary={t("plugin.techDetails")}><pre className="research-json-readout">{JSON.stringify({
                    credibility: report.credibility,
                    identity: report.identity,
                    account: report.account,
                    risk_policy: report.risk_policy,
                    pine_risk_stops: report.pine_risk_stops,
                    execution_assumptions: report.execution_assumptions,
                    hashes: report.hashes,
                    ...(external ? { external_provider: external } : {}),
                    equity_points: chart?.equity_curve.length ?? report.equity_curve?.length ?? 0,
                  }, null, 2)}</pre></Disclosure>}
                  {tab === "TRADES" && (
                    <div className="research-trade-table-wrap"><table><thead><tr><th>{t("research.results.trade")}</th><th>{t("research.results.side")}</th><th>{t("research.results.entry")}</th><th>{t("research.results.exit")}</th><th>{t("research.results.netPnl")}</th></tr></thead><tbody>{report.trades.slice(0, 500).map((trade, index) => <tr key={String(trade.trade_id ?? index)}><td>{String(trade.trade_id ?? index + 1)}</td><td>{String(trade.side ?? "—")}</td><td>{String(trade.entry_time_ms ?? "—")}</td><td>{String(trade.exit_time_ms ?? "—")}</td><td data-value-tone={Number(trade.net_pnl) > 0 ? "positive" : Number(trade.net_pnl) < 0 ? "negative" : undefined}>{String(trade.net_pnl ?? "—")}</td></tr>)}</tbody></table></div>
                  )}
                  {tab === "TRACE" && <>
                    <div className="research-button-row">
                      <Button size="sm" disabled={busy || (Boolean(external) && !runtime.view.capabilities?.flags.BACKTEST_EXTERNAL_PROVIDER_ENABLED)} onClick={() => void runtime.actions.loadSignalTrace()}>{t("research.results.trace")}</Button>
                      {external && runtime.view.externalTraceHasMore && <Button size="sm" variant="ghost" disabled={busy} onClick={() => void runtime.actions.loadSignalTrace(runtime.view.externalTraceNext)}>{t("strategyReview.nextPage")}</Button>}
                    </div>
                    <pre className="research-json-readout">{JSON.stringify(external ? runtime.view.externalTrace : signalTrace.slice(0, 1_000), null, 2)}</pre>
                  </>}
                  {tab === "COMPARE" && <pre className="research-json-readout">{JSON.stringify(runComparison ?? { message: t("research.results.compareEmpty") }, null, 2)}</pre>}
                  {tab === "QUALITY" && <pre className="research-json-readout">{JSON.stringify({
                    data_quality: report.data_quality,
                    quality: report.performance?.quality,
                    reconciliation: report.performance?.reconciliation,
                    fill_model: report.fill_model,
                    fill_trace: report.fill_trace,
                    unmodeled: report.unmodeled,
                    suitable_for: report.suitable_for,
                    not_suitable_for: report.not_suitable_for,
                  }, null, 2)}</pre>}
                </div>
              </TabPanel>
            </>
          )}
        </>
      ) : <p className="research-empty">{t("research.results.empty")}</p>}
    </ResearchPanelFrame>
  );
}
