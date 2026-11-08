import { useCallback, useEffect, useState } from "react";
import { chartQuickReplayKey, normalizeChartQuickReplay, type ChartQuickReplayState, type UpdateChartQuickReplay } from "../features/chart-workspace/chartQuickReplayState.js";
import { versionedReviewJournalApi } from "../features/readonly-accounts/reviewApi.js";
import { tradingApi } from "../features/trading-accounts/tradingApi.js";
import { tradingErrorMessage } from "../features/trading-accounts/tradingErrors.js";
import type { QuickReplayRequest } from "../features/trading-accounts/tradingTypes.js";

export function useChartQuickReplay(saved: ChartQuickReplayState | undefined, update: (change: UpdateChartQuickReplay) => void) {
  const key = saved && chartQuickReplayKey(saved);
  const { accountId, tradeId, interval, readonlyVersion } = saved ?? {};
  const [loaded, setLoaded] = useState<{ key: string; request: QuickReplayRequest } | null>(null);
  const [failed, setFailed] = useState<{ key: string; message: string } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const request = loaded && loaded.key === key ? loaded.request : null;

  useEffect(() => {
    if (!key || !accountId || !tradeId || !interval || request) return;
    const controller = new AbortController();
    const api = readonlyVersion ? versionedReviewJournalApi(readonlyVersion) : tradingApi;
    api.trade(accountId, tradeId, controller.signal).then(trade => {
      if (controller.signal.aborted) return;
      if (trade.id !== tradeId || trade.accountId !== accountId || trade.readonlySource?.version !== readonlyVersion) {
        throw new Error("Saved replay trade does not match its account or version");
      }
      setLoaded({ key, request: { accountId, trade, interval, api } });
    }).catch(error => {
      if (!controller.signal.aborted) setFailed({ key, message: tradingErrorMessage(error) });
    });
    return () => controller.abort();
  }, [accountId, attempt, interval, key, readonlyVersion, request, tradeId]);

  const open = useCallback((next: QuickReplayRequest) => {
    const state = normalizeChartQuickReplay({ accountId: next.accountId, tradeId: next.trade.id,
      readonlyVersion: next.trade.readonlySource?.version, interval: next.interval });
    if (!state) return;
    setLoaded({ key: chartQuickReplayKey(state), request: next });
    setFailed(null);
    update(() => state);
  }, [update]);

  const exit = useCallback(() => {
    setLoaded(null);
    setFailed(null);
    update(current => current && chartQuickReplayKey(current) === key ? undefined : current);
  }, [key, update]);

  const save = useCallback((cursorSec: number, step: string) => {
    update(current => current && chartQuickReplayKey(current) === key ? { ...current, cursorSec, step } : current);
  }, [key, update]);

  const retry = useCallback(() => {
    setFailed(null);
    setAttempt(value => value + 1);
  }, []);
  return { key, request, open, exit, save, retry, error: failed && failed.key === key ? failed.message : null };
}
