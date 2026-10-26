import { useEffect, useMemo, useSyncExternalStore } from "react";
import { tradingAccountsStore, type TradingAccountsState } from "./tradingAccountsStore.js";
import type { TradingAccount } from "./tradingTypes.js";

export { tradingErrorMessage } from "./tradingAccountsStore.js";

export interface TradingAccountsRuntime {
  view: TradingAccountsState;
  actions: {
    select(accountId: string): void;
    refresh(): Promise<void>;
    refreshJournal(): Promise<void>;
    createAccount(body: Record<string, unknown>): Promise<TradingAccount>;
    clearError(): void;
    reportError(error: unknown): void;
  };
}

const actions: TradingAccountsRuntime["actions"] = {
  select: (accountId) => tradingAccountsStore.select(accountId),
  refresh: () => tradingAccountsStore.refresh(),
  refreshJournal: () => tradingAccountsStore.refreshJournal(),
  createAccount: (body) => tradingAccountsStore.createAccount(body),
  clearError: () => tradingAccountsStore.clearError(),
  reportError: (cause) => tradingAccountsStore.reportError(cause),
};

/** The selected account's shared data; polling runs while `enabled`. */
export function useTradingAccountsRuntime(enabled: boolean): TradingAccountsRuntime {
  const view = useSyncExternalStore(tradingAccountsStore.subscribe, tradingAccountsStore.getSnapshot);
  useEffect(() => (enabled ? tradingAccountsStore.retain() : undefined), [enabled]);
  return useMemo(() => ({ view, actions }), [view]);
}
