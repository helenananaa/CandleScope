/**
 * Result views shared by every run family (ADR-BACKTEST-015 §4, step P1c).
 *
 * They read only `candlescope.run-result/1`, so a host run, a native Pine run and a
 * CandleScope-matched Pine run show the same summary and the same trade list. The
 * markup and classes are the chart tester's, so the dock keeps one visual language.
 * Values are shown as the run reports them; nothing here recomputes money.
 */
import { useEffect, useId, useMemo, useRef, useState, type UIEvent } from "react";
import { Button } from "../../../components/ui/index.js";
import { t } from "../../../i18n/index.js";
import { command } from "../../app-control/commandRegistry.js";
import { number, object } from "../../app-control/commandSchema.js";
import { useControlCommands } from "../../app-control/useControlCommands.js";
import { ResultMetric, type TradeExplanationSelection } from "../chart-tester/ChartStrategyResultViews.js";
import {
  CHART_STRATEGY_TRADE_ROW_HEIGHT, chartStrategyVirtualTradeWindow, chartStrategyWinRate, dateTime, formatChartStrategyNumber, signedClass,
} from "../chart-tester/chartStrategyResultModel.js";
import { runResultTradeFocus, runResultWinRate } from "./runResultViewModel.js";
import type { StrategyTradeFocus } from "../chart-tester/strategyTradeReview.js";
import type { TradeExplanationV1 } from "../backtestTypes.js";
import type { RunResult } from "./runResult.js";

export function RunResultSummary({ result, locale }: { result: RunResult; locale: string }) {
  const { summary, open_position: position } = result;
  const winRate = runResultWinRate(result);
  return (
    <div className="chart-strategy-result-metrics" data-testid="run-result-summary" data-authority={result.authority}>
      <ResultMetric label={t("chartTester.result.netPnl")} value={formatChartStrategyNumber(summary.net_profit ?? "—")}
        rawValue={summary.net_profit ?? "—"} />
      <ResultMetric label={t("report.equity")} value={formatChartStrategyNumber(summary.final_equity ?? "—")}
        rawValue={summary.final_equity ?? "—"}
        detail={t(result.authority === "SCRIPT" ? "native.equity" : "native.external.equity")} />
      <ResultMetric label={t("chartTester.result.trades")} value={String(summary.trade_count)}
        detail={t("chartTester.result.fills", { count: summary.fill_count })} />
      <ResultMetric label={t("chartTester.result.winRate")}
        value={winRate === null ? "—" : chartStrategyWinRate(winRate, locale)} rawValue={winRate === null ? "—" : String(winRate)} />
      {position && (
        <ResultMetric label={t("replay.shell.position")}
          value={`${t(position.side === "LONG" ? "report.long" : "report.short")} ${position.qty}`}
          rawValue={position.qty} detail={position.avg_price ? `@ ${formatChartStrategyNumber(position.avg_price, "price")}` : ""} />
      )}
    </div>
  );
}

export function RunResultTradeList({
  result,
  locale,
  active = true,
  onLocateTrade,
  onReviewTrade,
  onSelectExplanation,
}: {
  result: RunResult;
  locale: string;
  active?: boolean;
  onLocateTrade(timeMs: number): void;
  onReviewTrade?(trade: StrategyTradeFocus | null): void;
  onSelectExplanation?(selection: TradeExplanationSelection): void;
}) {
  const trades = result.trades;
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(224);
  const [selectedTradeId, setSelectedTradeId] = useState<string | null>(null);
  const selectedIndex = trades.findIndex((trade) => trade.id === selectedTradeId);
  const selectedTrade = trades[selectedIndex];
  const focus = useMemo(() => selectedTrade ? runResultTradeFocus(selectedTrade) : null, [selectedTrade]);
  useEffect(() => {
    if (!active) return;
    onReviewTrade?.(focus);
    return () => onReviewTrade?.(null);
  }, [active, focus, onReviewTrade]);
  const selectTrade = (index: number, focusRow = false) => {
    const trade = trades[index];
    if (!trade) return;
    setSelectedTradeId(trade.id);
    if (focusRow) requestAnimationFrame(() => viewportRef.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.focus({ preventScroll: true }));
    if (!onReviewTrade) onLocateTrade(runResultTradeFocus(trade).entryTimeMs);
    const viewport = viewportRef.current;
    if (viewport) {
      const top = index * CHART_STRATEGY_TRADE_ROW_HEIGHT;
      if (top < viewport.scrollTop || top + CHART_STRATEGY_TRADE_ROW_HEIGHT > viewport.scrollTop + viewport.clientHeight) {
        viewport.scrollTop = top;
        setScrollTop(top);
      }
    }
  };
  const window = useMemo(() => chartStrategyVirtualTradeWindow({ count: trades.length, scrollTop, viewportHeight }),
    [scrollTop, trades.length, viewportHeight]);
  const controlId = useId();
  useControlCommands(() => ({ id: `run-result-trades:${controlId}`, title: "Run result trade review",
    context: () => ({ source: result.source, selectedTradeId, active }),
    snapshot: () => ({ count: trades.length, selectedTradeId, selectedIndex, active }), commands: [
      command("rows", "Read a bounded page of the run's round trips.", object({ offset: number(0, 1e9, true), limit: number(1, 500, true) }),
        ({ offset, limit }) => trades.slice(offset, offset + limit), { readOnly: true }),
      command("select", "Select a round trip and review it on the chart.", object({ index: number(0, 1e9, true) }),
        ({ index }) => { if (!trades[index]) throw new Error("TRADE_UNAVAILABLE"); selectTrade(index); }, { available: () => active }),
    ] }));
  if (trades.length === 0) {
    return (
      <div className="chart-strategy-result-empty" data-testid="run-result-zero-trades">
        <strong>{t("chartTester.result.zeroTrades")}</strong>
        <span>{t(result.rejections.length ? "chartTester.result.rejectedNoTrades" : "chartTester.result.zeroTradesDetail")}</span>
      </div>
    );
  }
  const onScroll = (event: UIEvent<HTMLDivElement>) => {
    setScrollTop(event.currentTarget.scrollTop);
    setViewportHeight(event.currentTarget.clientHeight);
  };
  return (
    <div className="chart-strategy-trades" data-testid="run-result-trades" data-trade-count={trades.length} data-authority={result.authority}>
      <div className="strategy-trade-navigation" aria-label={t("strategyReview.navigation")}>
        <Button size="sm" disabled={selectedIndex <= 0} onClick={() => selectTrade(Math.max(0, selectedIndex - 1))}>{t("strategyReview.previous")}</Button>
        <span role="status">{selectedIndex < 0 ? t("strategyReview.select") : `${selectedIndex + 1} / ${trades.length}`}</span>
        <Button size="sm" disabled={selectedIndex === trades.length - 1} onClick={() => selectTrade(selectedIndex + 1)}>{t("strategyReview.next")}</Button>
      </div>
      <div className="chart-strategy-trade-head" aria-hidden="true">
        <span>{t("chartTester.result.trade")}</span><span>{t("chartTester.result.side")}</span>
        <span>{t("chartTester.result.entry")}</span><span>{t("chartTester.result.exit")}</span>
        <span>{t("chartTester.result.netPnl")}</span><span>{t("chartTester.result.fees")}</span>
      </div>
      <div ref={viewportRef} className="chart-strategy-trade-viewport" role="grid" aria-rowcount={trades.length} onScroll={onScroll}>
        <div className="chart-strategy-trade-spacer" style={{ height: `${window.totalHeight}px` }}>
          <div style={{ transform: `translateY(${window.offsetTop}px)` }}>
            {trades.slice(window.start, window.end).map((trade, offset) => {
              const index = window.start + offset;
              const selected = selectedTradeId === trade.id;
              return (
                <button
                  key={`${trade.id}:${index}`}
                  type="button"
                  role="row"
                  aria-rowindex={index + 1}
                  aria-selected={selected}
                  className={selected ? "chart-strategy-trade-row selected" : "chart-strategy-trade-row"}
                  style={{ height: `${CHART_STRATEGY_TRADE_ROW_HEIGHT}px` }}
                  onKeyDown={(event) => {
                    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
                    event.preventDefault();
                    selectTrade(Math.max(0, Math.min(trades.length - 1, index + (event.key === "ArrowDown" ? 1 : -1))), true);
                  }}
                  onClick={() => {
                    selectTrade(index);
                    const items = [
                      ...(trade.entry_explanation ? [{ label: t("chartTester.explain.entry"), explanation: trade.entry_explanation as unknown as TradeExplanationV1 }] : []),
                      ...(trade.exit_explanation ? [{ label: t("chartTester.explain.exit"), explanation: trade.exit_explanation as unknown as TradeExplanationV1 }] : []),
                    ];
                    if (items.length > 0) onSelectExplanation?.({ id: trade.id, title: t("chartTester.explain.tradeTitle", { trade: trade.id }), items });
                  }}
                >
                  <span>{trade.id}</span>
                  <span>{t(trade.side === "LONG" ? "report.long" : "report.short")} {trade.qty}</span>
                  <span title={`${trade.entry_price} · ${dateTime(trade.entry_time_ms, locale)}`}>{formatChartStrategyNumber(trade.entry_price, "price")}</span>
                  <span title={`${trade.exit_price} · ${dateTime(trade.exit_time_ms, locale)}`}>{formatChartStrategyNumber(trade.exit_price, "price")}</span>
                  <span title={trade.net_pnl ?? "—"} className={signedClass(trade.net_pnl ?? "")}>{formatChartStrategyNumber(trade.net_pnl ?? "—")}</span>
                  <span title={trade.fees ?? "—"}>{trade.fees === null ? "—" : formatChartStrategyNumber(trade.fees)}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
