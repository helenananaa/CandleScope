import { useEffect, useState } from "react";
import { tradingErrorMessage } from "./tradingAccountsStore.js";
import { tradingApi } from "./tradingApi.js";
import type { TradingStats } from "./tradingTypes.js";

export interface TradingStatsState {
  stats: TradingStats | null;
  loading: boolean;
  error: string | null;
}

const IDLE: TradingStatsState = { stats: null, loading: false, error: null };

/**
 * Closed-trade statistics of one account. Reloads when the account, the
 * filters or `revision` (closed trades, journal edits) change; the previous
 * result of the same account stays visible while the next one loads.
 */
export function useTradingStats(
  accountId: string | null,
  fromMs: number | null,
  tag: string | null,
  revision: string,
): TradingStatsState {
  const [state, setState] = useState<TradingStatsState>(IDLE);

  useEffect(() => {
    if (accountId === null) {
      setState(IDLE);
      return undefined;
    }
    const controller = new AbortController();
    setState((previous) => ({
      stats: previous.stats?.accountId === accountId ? previous.stats : null,
      loading: true,
      error: null,
    }));
    tradingApi.stats(accountId, { fromMs, tags: tag === null ? [] : [tag] }, controller.signal)
      .then((stats) => setState({ stats, loading: false, error: null }))
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setState((previous) => ({ ...previous, loading: false, error: tradingErrorMessage(cause) }));
      });
    return () => controller.abort();
  }, [accountId, fromMs, tag, revision]);

  return state;
}
