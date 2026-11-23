import { Fragment, useCallback, useEffect, useId, useState, type ReactNode } from "react";
import { Icon } from "../../components/icons/Icon.js";
import { Badge, Button, EmptyState, IconButton, InlineAlert, Select, TabPanel, Tabs } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import ContinuousRunAccount from "../backtest/continuous/ContinuousRunAccount.js";
import { useStrategyDataManager } from "../market-data/useStrategyDataManager.js";
import AddAccountDialog from "./AddAccountDialog.js";
import ManualFillForm from "./ManualFillForm.js";
import PracticeOrderTicket, { type PlanDraft } from "./PracticeOrderTicket.js";
import TradeJournalDrawer, { type JournalTarget } from "./TradeJournalDrawer.js";
import TradingStatsView from "./TradingStatsView.js";
import { forwardAccounts, forwardRunFromOption, rememberForwardRun, rememberedForwardRun, type ForwardAccount } from "./forwardAccounts.js";
import { planLevelParts, planLevels } from "./journalRender.js";
import { tradingApi } from "./tradingApi.js";
import {
  formatAmount,
  formatDateTime,
  formatPrice,
  formatQty,
  formatSigned,
  pnlTone,
} from "./tradingFormat.js";
import type { QuickReplayRequest, Trade, TradingChartContext } from "./tradingTypes.js";
import { useTradingAccountsRuntime } from "./useTradingAccountsRuntime.js";

type Tab = "trade" | "positions" | "history" | "journal" | "stats";
const TABS: readonly Tab[] = ["trade", "positions", "history", "journal", "stats"];

/** Long and short follow the chart's up and down colours, which the user may swap. */
export function DirectionBadge({ direction, children }: { direction: "long" | "short"; children: ReactNode }) {
  return <Badge className={`trading-dir-${direction}`}>{children}</Badge>;
}

export interface TradingAccountsPanelProps {
  context: TradingChartContext;
  onOpenQuickReplay(request: QuickReplayRequest): void;
  onRequestClose?: () => void;
}

export default function TradingAccountsPanel({ context, onOpenQuickReplay, onRequestClose }: TradingAccountsPanelProps) {
  useLocale();
  const runtime = useTradingAccountsRuntime(true);
  const { selected, summary, trades, entries } = runtime.view;
  const [tab, setTab] = useState<Tab>("trade");
  const [adding, setAdding] = useState(false);
  const [journal, setJournal] = useState<JournalTarget | null>(null);
  const tabsId = useId();
  // Forward runs are listed beside practice accounts, each with its own read-only ledger (ADR-BACKTEST-015 P6e).
  const continuous = useStrategyDataManager()?.continuous ?? null;
  const [forwardRuns, setForwardRuns] = useState<ForwardAccount[]>([]);
  const [forwardId, setForwardId] = useState<string | null>(rememberedForwardRun);
  useEffect(() => {
    if (!continuous) return;
    const abort = new AbortController();
    void continuous.catalog(abort.signal).then((catalog) => {
      if (!abort.signal.aborted) setForwardRuns(forwardAccounts(catalog.runs));
    }).catch(() => { /* Without the forward run list the page lists practice accounts only. */ });
    return () => abort.abort();
  }, [continuous]);
  const forward = forwardRuns.find((run) => run.runId === forwardId) ?? null;
  const chooseAccount = (option: string) => {
    const runId = forwardRunFromOption(option);
    setJournal(null);
    setForwardId(runId);
    rememberForwardRun(runId);
    if (runId === null) runtime.actions.select(option);
  };

  const refresh = runtime.actions.refresh;
  const openReplay = useCallback((trade: Trade) => {
    if (!selected) return;
    onOpenQuickReplay({
      accountId: selected.id,
      trade,
      interval: trade.symbol === context.symbol ? context.interval : "15m",
    });
  }, [context.interval, context.symbol, onOpenQuickReplay, selected]);

  const closePosition = async (trade: Trade) => {
    if (!selected) return;
    try {
      await tradingApi.placeOrder(selected.id, {
        exchange: trade.exchange,
        marketType: trade.marketType,
        symbol: trade.symbol,
        side: trade.direction === "long" ? "sell" : "buy",
        type: "market",
        qty: trade.openQty,
        reduceOnly: true,
        ...(selected.settings.positionMode === "HEDGE" && trade.marketType === "futures"
          ? { positionSide: trade.direction === "long" ? "LONG" : "SHORT", positionEffect: "close", tradeId: trade.id } : {}),
        ...(trade.exchange === context.exchange && trade.marketType === context.marketType && trade.symbol === context.symbol && context.lastPrice ? { referencePrice: String(context.lastPrice) } : {}),
      });
      await refresh();
    } catch (cause) {
      runtime.actions.reportError(cause);
    }
  };

  const cancelOrder = async (orderId: string) => {
    if (!selected) return;
    try {
      await tradingApi.cancelOrder(selected.id, orderId);
      await refresh();
    } catch (cause) {
      runtime.actions.reportError(cause);
    }
  };

  const planTrade = (draft: PlanDraft | null) => setJournal({ kind: "plan", draft });

  if (runtime.view.unavailable) {
    return (
      <div className="trading-panel">
        <EmptyState className="trading-empty" tone="warning" title={t("trading.title")} description={t("trading.unavailable")} />
      </div>
    );
  }

  const closedTrades = trades.filter((trade) => trade.status === "closed");
  const feedsBehind = (summary?.feeds ?? []).filter((feed) => feed.status !== "live");
  // Stats reload when a trade closes or a journal entry changes (tags, plan).
  const statsRevision = `${summary?.closedTrades ?? 0}:${entries.length}:${
    entries.reduce((latest, entry) => Math.max(latest, entry.updatedAtMs), 0)}`;

  return (
    <div className="trading-panel" data-account-kind={forward ? "forward" : selected?.kind ?? "none"}>
      <header className="trading-panel-header">
        {runtime.view.accounts.length > 0 || forwardRuns.length > 0 ? (
          <Select
            size="sm"
            className="trading-account-select"
            aria-label={t("trading.account")}
            value={forward?.option ?? selected?.id ?? ""}
            onChange={(event) => chooseAccount(event.target.value)}
          >
            {!forward && !selected && <option value="" disabled>{t("trading.title")}</option>}
            {runtime.view.accounts.map((account) => (
              <option key={account.id} value={account.id}>{account.name}</option>
            ))}
            {forwardRuns.length > 0 && (
              <optgroup label={t("trading.forward.group")}>
                {forwardRuns.map((run) => <option key={run.option} value={run.option}>{run.label}</option>)}
              </optgroup>
            )}
          </Select>
        ) : (
          <strong className="trading-panel-title">{t("trading.title")}</strong>
        )}
        <IconButton size="sm" label={t("trading.add.title")} title={t("trading.add.title")} icon={<Icon name="plus" size={16} />} onClick={() => setAdding(true)} />
        {onRequestClose && (
          <IconButton size="sm" label={t("trading.close")} icon={<Icon name="close" size={16} />} onClick={onRequestClose} />
        )}
      </header>

      {forward && continuous ? (
        <>
          <div className="trading-mode">
            <Badge tone="accent">{t("trading.mode.forward")}</Badge>
            <Badge tone={forward.practice ? "accent" : "neutral"}>
              {t(forward.practice ? "trading.forward.rules.practice" : "trading.forward.rules.test")}
            </Badge>
          </div>
          <p className="trading-forward-note">{t("trading.forward.readonly")}</p>
          <div className="trading-forward-ledger" data-forward-run={forward.runId}>
            <ContinuousRunAccount key={forward.runId} manager={continuous} runId={forward.runId} />
          </div>
        </>
      ) : selected === null ? (
        <EmptyState
          className="trading-empty"
          title={t("trading.title")}
          description={t("trading.empty")}
          action={<Button variant="primary" size="sm" onClick={() => setAdding(true)}>{t("trading.add.title")}</Button>}
        />
      ) : (
        <>
          <div className="trading-mode">
            <Badge tone={selected.kind === "practice" ? "accent" : "neutral"}>
              {t(selected.kind === "practice" ? "trading.mode.practice" : "trading.mode.manual")}
            </Badge>
            {summary && selected.kind === "practice" && (
              <span className="trading-equity">
                {t("trading.equity")} <strong>{summary.valuationStatus === "unknown" ? "—" : formatAmount(summary.equity)}</strong>
                {summary.valuationStatus === "stale" && <small>{t("pane.q.estimated")}</small>}
                <span data-tone={pnlTone(summary.unrealizedPnl)}> {summary.valuationStatus === "unknown" ? "—" : formatSigned(summary.unrealizedPnl)}</span>
              </span>
            )}
            {summary && selected.kind === "manual" && (
              <span className="trading-equity">
                {t("trading.realized")} <strong data-tone={pnlTone(summary.balance)}>{formatSigned(summary.balance)}</strong>
              </span>
            )}
          </div>
          {feedsBehind.map((feed) => (
            <InlineAlert key={`${feed.exchange}:${feed.marketType}:${feed.symbol}`} tone="warning" className="trading-notice">
              {t(feed.status === "catching_up" ? "trading.feed.catchingUp" : "trading.feed.unavailable", { symbol: feed.symbol })}
            </InlineAlert>
          ))}
          {runtime.view.error && (
            <InlineAlert
              tone="danger"
              className="trading-notice"
              action={<Button size="sm" variant="ghost" onClick={runtime.actions.clearError}>{t("trading.dismiss")}</Button>}
            >
              {runtime.view.error}
            </InlineAlert>
          )}
          <Tabs
            id={tabsId}
            className="trading-tabs"
            label={t("trading.title")}
            value={tab}
            onChange={setTab}
            tabs={TABS.map((item) => ({
              value: item,
              label: item === "history" && closedTrades.some((trade) => trade.needsReview)
                ? <>{t("trading.tab.history")}<span className="trading-dot" role="img" aria-label={t("trading.needsReview")} /></>
                : t(`trading.tab.${item}` as const),
              ...(item === "positions" && summary && summary.positions.length > 0 ? { badge: summary.positions.length } : {}),
            }))}
          />

          <TabPanel tabsId={tabsId} value={tab} className="trading-tab-body">
            {tab === "trade" && (
              selected.kind === "practice" ? (
                <PracticeOrderTicket
                  account={selected}
                  summary={summary}
                  context={context}
                  onPlaced={() => { void refresh(); }}
                  onPlanTrade={planTrade}
                />
              ) : (
                <ManualFillForm account={selected} context={context} onAdded={() => { void refresh(); }} />
              )
            )}

            {tab === "positions" && (
              <div className="trading-list">
                {(summary?.positions ?? []).length === 0 && <p className="trading-empty-line">{t("trading.positions.empty")}</p>}
                {(summary?.positions ?? []).map((trade) => (
                  <article key={trade.id} className="trading-row">
                    <div className="trading-row-main">
                      <strong>{trade.symbol}</strong>
                      <DirectionBadge direction={trade.direction}>
                        {t(trade.direction === "long" ? "trading.long" : "trading.short")} {formatQty(trade.openQty)}
                      </DirectionBadge>
                      <span data-tone={pnlTone(trade.unrealizedPnl)} className="trading-row-pnl">{formatSigned(trade.unrealizedPnl)}</span>
                    </div>
                    <div className="trading-row-sub">
                      {t("trading.positions.avgMark", { avg: formatPrice(trade.avgEntryPrice), mark: formatPrice(trade.markPrice) })}
                    </div>
                    <div className="trading-row-actions">
                      <Button size="sm" variant="ghost" onClick={() => setJournal({ kind: "trade", tradeId: trade.id })}>{t("trading.note")}</Button>
                      <Button size="sm" variant="ghost" onClick={() => openReplay(trade)}>{t("trading.replay.short")}</Button>
                      {selected.kind === "practice" && (
                        <Button size="sm" variant="ghost" className="trading-close-position" onClick={() => { void closePosition(trade); }}>{t("trading.positions.close")}</Button>
                      )}
                    </div>
                  </article>
                ))}
                {(summary?.workingOrders ?? []).length > 0 && <h3 className="trading-subhead">{t("trading.orders.working")}</h3>}
                {(summary?.workingOrders ?? []).map((order) => (
                  <article key={order.id} className="trading-row" data-compact="true">
                    <div className="trading-row-main">
                      <strong>{order.symbol}</strong>
                      <DirectionBadge direction={(order.positionSide ? order.positionSide === "LONG" : order.side === "buy") ? "long" : "short"}>
                        {order.positionSide && t(order.positionSide === "LONG" ? "trading.long" : "trading.short")} {t(`trading.orderTag.${order.tag === "stop_loss" ? "stopLoss" : order.tag === "take_profit" ? "takeProfit" : order.type}` as const)}
                      </DirectionBadge>
                      <span>{formatQty(order.qty)} @ {formatPrice(order.limitPrice ?? order.stopPrice)}</span>
                    </div>
                    <div className="trading-row-actions">
                      <Button size="sm" variant="ghost" onClick={() => { void cancelOrder(order.id); }}>{t("trading.cancel")}</Button>
                    </div>
                  </article>
                ))}
              </div>
            )}

            {tab === "history" && (
              <div className="trading-list">
                {closedTrades.length === 0 && <p className="trading-empty-line">{t("trading.history.empty")}</p>}
                {closedTrades.map((trade) => (
                  <article key={trade.id} className="trading-row" data-clickable="true">
                    <button type="button" className="trading-row-button" onClick={() => setJournal({ kind: "trade", tradeId: trade.id })}>
                      <div className="trading-row-main">
                        <strong>{trade.symbol}</strong>
                        <DirectionBadge direction={trade.direction}>
                          {t(trade.direction === "long" ? "trading.long" : "trading.short")}
                        </DirectionBadge>
                        <span data-tone={pnlTone(trade.netPnl)} className="trading-row-pnl">
                          {formatSigned(trade.netPnl)}{trade.metrics?.netR ? ` · ${trade.metrics.netR}R` : ""}
                        </span>
                      </div>
                      <div className="trading-row-sub">
                        {formatDateTime(trade.openedAtMs)}
                        {trade.needsReview && <Badge tone="warning">{t("trading.needsReview")}</Badge>}
                      </div>
                    </button>
                    <div className="trading-row-actions">
                      <Button size="sm" variant="ghost" onClick={() => openReplay(trade)}>{t("trading.replay.short")}</Button>
                    </div>
                  </article>
                ))}
              </div>
            )}

            {tab === "journal" && (
              <div className="trading-list">
                <div className="trading-actions">
                  <Button size="sm" variant="primary" onClick={() => planTrade(null)}>
                    {t("trading.journal.newPlan", { symbol: context.symbol })}
                  </Button>
                </div>
                {entries.length === 0 && <p className="trading-empty-line">{t("trading.journal.empty")}</p>}
                {entries.map((entry) => {
                  // Same-minute plans share a time, so show what each one planned.
                  const plan = entry.kind === "note" ? planLevels(entry.fields) : null;
                  const levels = plan ? planLevelParts(plan) : [];
                  return (
                    <article key={entry.id} className="trading-row" data-clickable="true">
                      <button
                        type="button"
                        className="trading-row-button"
                        onClick={() => setJournal(entry.tradeId && entry.kind === "quick"
                          ? { kind: "trade", tradeId: entry.tradeId }
                          : { kind: "entry", entryId: entry.id })}
                      >
                        <div className="trading-row-main">
                          <strong>{entry.symbol}</strong>
                          <Badge tone={entry.kind === "note" && !entry.tradeId ? "accent" : "neutral"}>
                            {entry.kind === "quick"
                              ? t("trading.journal.quick")
                              : entry.tradeId ? t("trading.journal.tradeNote") : t("trading.journal.plan")}
                          </Badge>
                          {plan?.direction && (
                            <DirectionBadge direction={plan.direction}>
                              {t(plan.direction === "long" ? "trading.long" : "trading.short")}
                            </DirectionBadge>
                          )}
                          <time>{formatDateTime(entry.createdAtMs)}</time>
                        </div>
                        {levels.length > 0 && (
                          <div className="trading-row-levels">
                            {levels.map((part, index) => (
                              <Fragment key={part}>{index > 0 && " · "}<span>{part}</span></Fragment>
                            ))}
                          </div>
                        )}
                        <div className="trading-row-sub">
                          {entry.kind === "quick" ? entry.body : (entry.fields.entryBasis ?? entry.fields.strategyTag ?? "")}
                        </div>
                      </button>
                    </article>
                  );
                })}
              </div>
            )}

            {tab === "stats" && (
              <TradingStatsView key={selected.id} account={selected} revision={statsRevision} />
            )}
          </TabPanel>
        </>
      )}

      {adding && (
        <AddAccountDialog onCreate={runtime.actions.createAccount} onClose={() => setAdding(false)} />
      )}
      {journal && selected && !forward && (
        <TradeJournalDrawer
          key={`${selected.id}:${JSON.stringify(journal)}:${journal.kind === "plan" ? `${context.exchange}:${context.marketType}:${context.symbol}` : ""}`}
          account={selected}
          target={journal}
          context={context}
          onClose={() => setJournal(null)}
          onChanged={() => { void refresh(); }}
          onOpenQuickReplay={(trade) => openReplay(trade)}
        />
      )}
    </div>
  );
}
