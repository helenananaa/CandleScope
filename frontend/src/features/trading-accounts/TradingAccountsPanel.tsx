import { Fragment, useCallback, useState } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import AddAccountDialog from "./AddAccountDialog.js";
import ManualFillForm from "./ManualFillForm.js";
import PracticeOrderTicket, { type PlanDraft } from "./PracticeOrderTicket.js";
import TradeJournalDrawer, { type JournalTarget } from "./TradeJournalDrawer.js";
import TradingStatsView from "./TradingStatsView.js";
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
import "./tradingAccounts.css";

type Tab = "trade" | "positions" | "history" | "journal" | "stats";

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
        ...(trade.symbol === context.symbol && context.lastPrice ? { referencePrice: String(context.lastPrice) } : {}),
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
        <p className="trading-empty">{t("trading.unavailable")}</p>
      </div>
    );
  }

  const closedTrades = trades.filter((trade) => trade.status === "closed");
  const feedsBehind = (summary?.feeds ?? []).filter((feed) => feed.status !== "live");
  // Stats reload when a trade closes or a journal entry changes (tags, plan).
  const statsRevision = `${summary?.closedTrades ?? 0}:${entries.length}:${
    entries.reduce((latest, entry) => Math.max(latest, entry.updatedAtMs), 0)}`;

  return (
    <div className="trading-panel" data-account-kind={selected?.kind ?? "none"}>
      <header className="trading-panel-header">
        {runtime.view.accounts.length > 0 ? (
          <select
            className="trading-account-select"
            aria-label={t("trading.account")}
            value={selected?.id ?? ""}
            onChange={(event) => runtime.actions.select(event.target.value)}
          >
            {runtime.view.accounts.map((account) => (
              <option key={account.id} value={account.id}>{account.name}</option>
            ))}
          </select>
        ) : (
          <strong className="trading-panel-title">{t("trading.title")}</strong>
        )}
        <button type="button" className="trading-icon-button" aria-label={t("trading.add.title")} title={t("trading.add.title")} onClick={() => setAdding(true)}>+</button>
        {onRequestClose && (
          <button type="button" className="trading-icon-button" aria-label={t("trading.close")} onClick={onRequestClose}>×</button>
        )}
      </header>

      {selected === null ? (
        <div className="trading-empty">
          <p>{t("trading.empty")}</p>
          <button type="button" className="trading-button" data-variant="primary" onClick={() => setAdding(true)}>{t("trading.add.title")}</button>
        </div>
      ) : (
        <>
          <div className="trading-mode">
            <span className="trading-badge" data-tone={selected.kind === "practice" ? "accent" : "muted"}>
              {t(selected.kind === "practice" ? "trading.mode.practice" : "trading.mode.manual")}
            </span>
            {summary && selected.kind === "practice" && (
              <span className="trading-equity">
                {t("trading.equity")} <strong>{formatAmount(summary.equity)}</strong>
                <span data-tone={pnlTone(summary.unrealizedPnl)}> {formatSigned(summary.unrealizedPnl)}</span>
              </span>
            )}
            {summary && selected.kind === "manual" && (
              <span className="trading-equity">
                {t("trading.realized")} <strong data-tone={pnlTone(summary.balance)}>{formatSigned(summary.balance)}</strong>
              </span>
            )}
          </div>
          {feedsBehind.map((feed) => (
            <p key={`${feed.exchange}:${feed.marketType}:${feed.symbol}`} className="trading-warning" role="status">
              {t(feed.status === "catching_up" ? "trading.feed.catchingUp" : "trading.feed.unavailable", { symbol: feed.symbol })}
            </p>
          ))}
          {runtime.view.error && (
            <p className="trading-error" role="alert">
              {runtime.view.error}
              <button type="button" className="trading-link" onClick={runtime.actions.clearError}>{t("trading.dismiss")}</button>
            </p>
          )}
          <nav className="trading-tabs" role="tablist" aria-label={t("trading.title")}>
            {(["trade", "positions", "history", "journal", "stats"] as const).map((item) => (
              <button
                key={item}
                type="button"
                role="tab"
                aria-selected={tab === item}
                onClick={() => setTab(item)}
              >
                {t(`trading.tab.${item}` as const)}
                {item === "positions" && summary && summary.positions.length > 0 && (
                  <span className="trading-count">{summary.positions.length}</span>
                )}
                {item === "history" && closedTrades.some((trade) => trade.needsReview) && (
                  <span className="trading-dot" aria-label={t("trading.needsReview")} />
                )}
              </button>
            ))}
          </nav>

          <div className="trading-tab-body" role="tabpanel">
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
                      <span className="trading-badge" data-tone={trade.direction === "long" ? "up" : "down"}>
                        {t(trade.direction === "long" ? "trading.long" : "trading.short")} {formatQty(trade.openQty)}
                      </span>
                      <span data-tone={pnlTone(trade.unrealizedPnl)} className="trading-row-pnl">{formatSigned(trade.unrealizedPnl)}</span>
                    </div>
                    <div className="trading-row-sub">
                      {t("trading.positions.avgMark", { avg: formatPrice(trade.avgEntryPrice), mark: formatPrice(trade.markPrice) })}
                    </div>
                    <div className="trading-row-actions">
                      <button type="button" className="trading-link" onClick={() => setJournal({ kind: "trade", tradeId: trade.id })}>{t("trading.note")}</button>
                      <button type="button" className="trading-link" onClick={() => openReplay(trade)}>{t("trading.replay.short")}</button>
                      {selected.kind === "practice" && (
                        <button type="button" className="trading-link" data-tone="down" onClick={() => { void closePosition(trade); }}>{t("trading.positions.close")}</button>
                      )}
                    </div>
                  </article>
                ))}
                {(summary?.workingOrders ?? []).length > 0 && <h3 className="trading-subhead">{t("trading.orders.working")}</h3>}
                {(summary?.workingOrders ?? []).map((order) => (
                  <article key={order.id} className="trading-row" data-compact="true">
                    <div className="trading-row-main">
                      <strong>{order.symbol}</strong>
                      <span className="trading-badge" data-tone={order.side === "buy" ? "up" : "down"}>
                        {t(`trading.orderTag.${order.tag === "stop_loss" ? "stopLoss" : order.tag === "take_profit" ? "takeProfit" : order.type}` as const)}
                      </span>
                      <span>{formatQty(order.qty)} @ {formatPrice(order.limitPrice ?? order.stopPrice)}</span>
                    </div>
                    <div className="trading-row-actions">
                      <button type="button" className="trading-link" onClick={() => { void cancelOrder(order.id); }}>{t("trading.cancel")}</button>
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
                        <span className="trading-badge" data-tone={trade.direction === "long" ? "up" : "down"}>
                          {t(trade.direction === "long" ? "trading.long" : "trading.short")}
                        </span>
                        <span data-tone={pnlTone(trade.netPnl)} className="trading-row-pnl">
                          {formatSigned(trade.netPnl)}{trade.metrics?.netR ? ` · ${trade.metrics.netR}R` : ""}
                        </span>
                      </div>
                      <div className="trading-row-sub">
                        {formatDateTime(trade.openedAtMs)}
                        {trade.needsReview && <em className="trading-badge" data-tone="warning">{t("trading.needsReview")}</em>}
                      </div>
                    </button>
                    <div className="trading-row-actions">
                      <button type="button" className="trading-link" onClick={() => openReplay(trade)}>{t("trading.replay.short")}</button>
                    </div>
                  </article>
                ))}
              </div>
            )}

            {tab === "journal" && (
              <div className="trading-list">
                <div className="trading-actions">
                  <button type="button" className="trading-button" data-variant="primary" onClick={() => planTrade(null)}>
                    {t("trading.journal.newPlan", { symbol: context.symbol })}
                  </button>
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
                          <span className="trading-badge" data-tone={entry.kind === "note" && !entry.tradeId ? "info" : "muted"}>
                            {entry.kind === "quick"
                              ? t("trading.journal.quick")
                              : entry.tradeId ? t("trading.journal.tradeNote") : t("trading.journal.plan")}
                          </span>
                          {plan?.direction && (
                            <span className="trading-badge" data-tone={plan.direction === "long" ? "up" : "down"}>
                              {t(plan.direction === "long" ? "trading.long" : "trading.short")}
                            </span>
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
          </div>
        </>
      )}

      {adding && (
        <AddAccountDialog onCreate={runtime.actions.createAccount} onClose={() => setAdding(false)} />
      )}
      {journal && selected && (
        <TradeJournalDrawer
          key={JSON.stringify(journal)}
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
