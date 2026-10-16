import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "../../services/api.js";
import { tradingApi } from "./tradingApi.js";
import type {
  AccountSummary,
  JournalEntry,
  PlannedAccountKind,
  Trade,
  TradingAccount,
} from "./tradingTypes.js";

const SELECTED_ACCOUNT_KEY = "candlescope-trading-selected-account-v1";
const ACTIVE_POLL_MS = 2_000;
const IDLE_POLL_MS = 15_000;

function readSelected(): string | null {
  try {
    return globalThis.localStorage?.getItem(SELECTED_ACCOUNT_KEY) ?? null;
  } catch {
    return null;
  }
}

function writeSelected(accountId: string | null): void {
  try {
    if (accountId) globalThis.localStorage?.setItem(SELECTED_ACCOUNT_KEY, accountId);
    else globalThis.localStorage?.removeItem(SELECTED_ACCOUNT_KEY);
  } catch {
    // Selection is a convenience; the panel still works without storage.
  }
}

export function tradingErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    try {
      const parsed = JSON.parse(error.detail) as { message?: unknown };
      if (typeof parsed.message === "string") return parsed.message;
    } catch {
      // detail is plain text
    }
    return error.detail;
  }
  return error instanceof Error ? error.message : String(error);
}

export interface TradingAccountsRuntime {
  view: {
    accounts: TradingAccount[];
    plannedKinds: PlannedAccountKind[];
    selected: TradingAccount | null;
    summary: AccountSummary | null;
    trades: Trade[];
    entries: JournalEntry[];
    loading: boolean;
    error: string | null;
    unavailable: boolean;
  };
  actions: {
    select(accountId: string): void;
    refresh(): Promise<void>;
    refreshJournal(): Promise<void>;
    createAccount(body: Record<string, unknown>): Promise<TradingAccount>;
    clearError(): void;
    reportError(error: unknown): void;
  };
}

export function useTradingAccountsRuntime(enabled: boolean): TradingAccountsRuntime {
  const [accounts, setAccounts] = useState<TradingAccount[]>([]);
  const [plannedKinds, setPlannedKinds] = useState<PlannedAccountKind[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(readSelected);
  const [summary, setSummary] = useState<AccountSummary | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const selectedRef = useRef(selectedId);
  selectedRef.current = selectedId;

  const visibleAccounts = useMemo(() => accounts.filter((account) => !account.archived), [accounts]);
  const selected = visibleAccounts.find((account) => account.id === selectedId) ?? visibleAccounts[0] ?? null;

  const loadAccounts = useCallback(async () => {
    try {
      const response = await tradingApi.listAccounts();
      setAccounts(response.accounts);
      setPlannedKinds(response.plannedKinds);
      setUnavailable(false);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 503) setUnavailable(true);
      else setError(tradingErrorMessage(cause));
    }
  }, []);

  const loadAccountData = useCallback(async (accountId: string, signal?: AbortSignal) => {
    const [nextSummary, nextTrades] = await Promise.all([
      tradingApi.summary(accountId, signal),
      tradingApi.trades(accountId, signal),
    ]);
    if (selectedRef.current !== null && selectedRef.current !== accountId) return;
    setSummary(nextSummary);
    setTrades(nextTrades.trades);
  }, []);

  const refreshJournal = useCallback(async () => {
    if (!selected) return;
    try {
      const response = await tradingApi.journal(selected.id);
      setEntries(response.entries);
    } catch (cause) {
      setError(tradingErrorMessage(cause));
    }
  }, [selected]);

  const refresh = useCallback(async () => {
    if (!selected) return;
    setLoading(true);
    try {
      await Promise.all([loadAccountData(selected.id), refreshJournal()]);
      setError(null);
    } catch (cause) {
      setError(tradingErrorMessage(cause));
    } finally {
      setLoading(false);
    }
  }, [loadAccountData, refreshJournal, selected]);

  useEffect(() => {
    if (!enabled) return;
    void loadAccounts();
  }, [enabled, loadAccounts]);

  const selectedAccountId = selected?.id ?? null;
  useEffect(() => {
    setSummary(null);
    setTrades([]);
    setEntries([]);
    if (!enabled || selectedAccountId === null) return;
    void refresh();
    // refresh is keyed by the selected account; re-run only when it changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, selectedAccountId]);

  const active = summary !== null
    && summary.account.kind === "practice"
    && (summary.positions.length > 0 || summary.workingOrders.length > 0);
  useEffect(() => {
    if (!enabled || selectedAccountId === null) return undefined;
    const controller = new AbortController();
    const timer = window.setInterval(() => {
      void loadAccountData(selectedAccountId, controller.signal).catch(() => undefined);
    }, active ? ACTIVE_POLL_MS : IDLE_POLL_MS);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [active, enabled, loadAccountData, selectedAccountId]);

  const select = useCallback((accountId: string) => {
    setSelectedId(accountId);
    writeSelected(accountId);
  }, []);

  const createAccount = useCallback(async (body: Record<string, unknown>) => {
    const account = await tradingApi.createAccount(body);
    await loadAccounts();
    select(account.id);
    return account;
  }, [loadAccounts, select]);

  return {
    view: {
      accounts: visibleAccounts,
      plannedKinds,
      selected,
      summary,
      trades,
      entries,
      loading,
      error,
      unavailable,
    },
    actions: {
      select,
      refresh,
      refreshJournal,
      createAccount,
      clearError: () => setError(null),
      reportError: (cause: unknown) => setError(tradingErrorMessage(cause)),
    },
  };
}
