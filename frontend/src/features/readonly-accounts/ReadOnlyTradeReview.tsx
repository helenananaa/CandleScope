import { useCallback, useEffect, useMemo, useState } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import TradeJournalDrawer from "../trading-accounts/TradeJournalDrawer.js";
import type { QuickReplayRequest, Trade, TradingChartContext } from "../trading-accounts/tradingTypes.js";
import { formatDateTime, formatSigned } from "../trading-accounts/tradingFormat.js";
import { AccountApiError } from "./accountApi.js";
import { accountErrorHelp } from "./accountErrors.js";
import { getReviewTrades, reviewJournalApi, type ReviewListing } from "./reviewApi.js";
import "../trading-accounts/tradingAccounts.css";

export interface ReadOnlyReviewBinding {
  context: TradingChartContext;
  onOpenQuickReplay(request: QuickReplayRequest): void;
}

export default function ReadOnlyTradeReview({ binding }: { binding?: ReadOnlyReviewBinding | undefined }) {
  useLocale();
  const [listing, setListing] = useState<ReviewListing | null>(null);
  const [selected, setSelected] = useState<Trade | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const refresh = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try { const next = await getReviewTrades(signal); if (!signal?.aborted) { setListing(next); setError(null); } }
    catch (cause) { if (!signal?.aborted) setError(cause instanceof AccountApiError ? cause.code : "ACCOUNT_UNAVAILABLE"); }
    finally { if (!signal?.aborted) setLoading(false); }
  }, []);
  useEffect(() => { const controller = new AbortController(); void refresh(controller.signal); return () => controller.abort(); }, [refresh]);
  const target = useMemo(() => selected ? { kind: "trade" as const, tradeId: selected.id } : null, [selected]);
  const api = useMemo(() => selected ? reviewJournalApi(selected) : null, [selected]);
  const stats = listing?.stats;
  return <section className="readonly-review">
    <p className="readonly-account-help">{t("account.review.scope")}</p>
    <button type="button" disabled={loading} onClick={() => { void refresh(); }}>{t(loading ? "account.loading" : "account.refresh")}</button>
    {error && <p role="alert">{accountErrorHelp(error)}</p>}
    {stats && <>
      <p>{t("account.review.sample", { count: stats.count, wins: stats.wins, cached: stats.cachedCount })}</p>
      <dl className="readonly-review-stats">
        <dt>{t("account.check.exchangePnl")}</dt><dd>{formatSigned(stats.realizedPnl)} USDT</dd>
        <dt>{t("account.review.fees")}</dt><dd>{stats.fees} USDT</dd>
        <dt>{t("account.review.funding")}</dt><dd>{formatSigned(stats.funding)} USDT</dd>
        <dt>{t("account.review.net")}</dt><dd>{formatSigned(stats.netPnl)} USDT</dd>
      </dl>
      <p className="readonly-account-help">{t("account.review.noR")}</p>
    </>}
    {listing && <>
      {listing.readError && <p role="alert">{accountErrorHelp(listing.readError)}</p>}
      {(!listing.current || stats?.cachedCount) ? <p role="status">{t("account.review.cached")}</p> : null}
      {listing.truncated && <p role="status">{t("account.check.truncated")}</p>}
      <details><summary>{t("account.review.coverage")}</summary>
        {listing.coverage.map((range, index) => <p key={index}>{range.kind}: {formatDateTime(range.start_ms)} – {formatDateTime(range.end_ms)}</p>)}
        {listing.gaps.map((range, index) => <p key={index}>{t("account.check.coverageGap")}: {formatDateTime(range.start_ms)} – {formatDateTime(range.end_ms)}</p>)}
      </details>
      <p>{t("account.check.unmatchedFills")}: {listing.unmatchedFills ?? 0}</p>
      {!listing.trades.length && <p>{t("account.review.empty")}</p>}
      <ul className="readonly-account-list">{listing.trades.map((trade) => <li key={trade.id}>
        <strong>{trade.readonlySource?.instrument} · {t(`trading.${trade.direction}`)}</strong>
        <p>{formatDateTime(trade.openedAtMs)} → {formatDateTime(trade.closedAtMs)}</p>
        <p>{t("account.review.net")}: {formatSigned(trade.netPnl)} USDT</p>
        <p className="readonly-account-help">{t("account.review.verified", { time: formatDateTime(trade.readonlySource?.verifiedAtMs) })}</p>
        <button type="button" disabled={!binding} onClick={() => setSelected(trade)}>{t("account.review.open")}</button>
      </li>)}</ul>
      {listing.excluded.length > 0 && <details><summary>{t("account.review.excluded", { count: listing.excluded.length })}</summary>
        {listing.excluded.map((row, index) => <p key={index}>{row.instrument} · {row.positionId}: {t(`account.check.${row.reason}`)}</p>)}
      </details>}
    </>}
    {selected && target && api && binding && <TradeJournalDrawer key={`${selected.id}:${selected.readonlySource?.version}`}
      account={{ id: selected.accountId }} target={target} api={api}
      context={binding.context} onClose={() => setSelected(null)} onChanged={() => { void refresh(); }}
      onOpenQuickReplay={(trade) => {
        binding.onOpenQuickReplay({ accountId: selected.accountId, trade, interval: binding.context.interval, api });
        setSelected(null);
      }} />}
  </section>;
}
