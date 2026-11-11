import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { normalizeChartAccountOverlay, type ChartAccountOverlaySettings } from "../chart-workspace/chartAccountOverlaySettings.js";
import type { MarketSeries } from "../market-data/marketDataTypes.js";
import { tradingAccountDataPool, type TradingAccountDataState } from "../trading-accounts/tradingAccountDataPool.js";
import { tradingAccountsStore } from "../trading-accounts/tradingAccountsStore.js";
import type { StudyJournalData, StudyJournalView } from "./historyStudyJournal.js";
import type { HistoryStudyDataManager } from "./historyStudyDataManager.js";
import { tradingErrorMessage } from "../trading-accounts/tradingErrors.js";

const empty: TradingAccountDataState = { accountId: "", summary: null, trades: [], entries: [], loading: false, error: null };
const noSubscribe = () => () => {};
const emptySnapshot = () => empty;

/** Original records remain in their account service. The existing observer
 * invalidates edits; the study manager owns bounded at-time reads/cancellation.
 * No market history or account state is copied or changed by navigation. */
export function useHistoryStudyJournal(manager: HistoryStudyDataManager, settingsInput: ChartAccountOverlaySettings | undefined,
  series: MarketSeries, cursorMs: number): StudyJournalView & { retry(): void } {
  const settings = normalizeChartAccountOverlay(settingsInput);
  const accounts = useSyncExternalStore(tradingAccountsStore.subscribe, tradingAccountsStore.getSnapshot);
  const follows = settings.accountId === null;
  useEffect(() => settings.notes && follows ? tradingAccountsStore.retain() : undefined, [follows, settings.notes]);
  const accountId = settings.notes ? settings.accountId ?? accounts.selected?.id ?? null : null;
  const accountName = accounts.accounts.find(account => account.id === accountId)?.name ?? accountId;
  const source = useMemo(() => accountId ? tradingAccountDataPool.account(accountId) : null, [accountId]);
  const data = useSyncExternalStore(source?.subscribe ?? noSubscribe, source?.getSnapshot ?? emptySnapshot);
  useEffect(() => source?.retain(), [source]);
  const noteSource = settings.noteSource ?? "all";
  const noteFilter = settings.noteFilter ?? "all";
  const key = JSON.stringify([accountId, series.exchange, series.marketType, series.symbol, cursorMs, noteSource, noteFilter]);
  const [loaded, setLoaded] = useState<{ key: string; data: StudyJournalData | null; error: string | null } | null>(null);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    if (!accountId) return;
    const controller = new AbortController();
    manager.journalAtTime(accountId, series, cursorMs, { noteSource, noteFilter }, controller.signal).then(result => {
      if (!controller.signal.aborted) setLoaded({ key, data: result, error: null });
    }).catch(error => { if (!controller.signal.aborted) setLoaded({ key, data: null, error: tradingErrorMessage(error) }); });
    return () => controller.abort();
    // The existing account observer's read cycle also invalidates text changes
    // while paused. It remains the sole owner of that account's polling.
  }, [accountId, cursorMs, data.entries, key, manager, noteFilter, noteSource, refresh, series]);
  const current = loaded?.key === key ? loaded : null;
  return useMemo(() => ({ enabled: settings.notes, accountId, accountName, cursorMs,
    loading: !!accountId && !current, error: current?.error ?? null,
    original: current?.data?.original ?? [], reviews: current?.data?.reviews ?? [], hasMore: current?.data?.hasMore ?? false,
    retry: () => setRefresh(value => value + 1) }),
  [accountId, accountName, current, cursorMs, settings.notes]);
}
