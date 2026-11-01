import { ApiError } from "../../services/api.js";
import { tradingApi } from "./tradingApi.js";
import { tradingAccountDataPool, type TradingAccountData } from "./tradingAccountDataPool.js";
import { tradingErrorMessage } from "./tradingErrors.js";
export { tradingErrorMessage } from "./tradingErrors.js";
import type {
  AccountSummary,
  JournalEntry,
  PlannedAccountKind,
  Trade,
  TradingAccount,
} from "./tradingTypes.js";

const SELECTED_ACCOUNT_KEY = "candlescope-trading-selected-account-v1";
const ACCOUNTS_RETRY_MS = 5_000;

export interface TradingAccountsState {
  accounts: TradingAccount[];
  plannedKinds: PlannedAccountKind[];
  selected: TradingAccount | null;
  summary: AccountSummary | null;
  trades: Trade[];
  entries: JournalEntry[];
  loading: boolean;
  error: string | null;
  unavailable: boolean;
}

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

/**
 * Account catalog and panel selection. Data belongs to the per-account pool,
 * so pinned charts do not change panel selection or duplicate its polling.
 */
class TradingAccountsStore {
  private allAccounts: TradingAccount[] = [];
  private selectedId: string | null = readSelected();
  private state: TradingAccountsState = {
    accounts: [],
    plannedKinds: [],
    selected: null,
    summary: null,
    trades: [],
    entries: [],
    loading: false,
    error: null,
    unavailable: false,
  };
  private readonly listeners = new Set<() => void>();
  private consumers = 0;
  private accountsRequested = false;
  private accountsFailed = false;
  private accountsRetry: ReturnType<typeof setTimeout> | null = null;
  private dataAccountId: string | null = null;
  private data: TradingAccountData | null = null;
  private releaseData: (() => void) | null = null;
  private unsubscribeData: (() => void) | null = null;

  getSnapshot = (): TradingAccountsState => this.state;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  /** Keeps data loading and polling alive until the returned release runs. */
  retain(): () => void {
    this.consumers += 1;
    if (this.consumers === 1) {
      if (!this.accountsRequested) void this.loadAccounts();
      this.syncSelection(true);
    }
    let released = false;
    return () => {
      if (released) return;
      released = true;
      this.consumers -= 1;
      if (this.consumers === 0) this.stopPolling();
    };
  }

  select(accountId: string): void {
    this.selectedId = accountId;
    writeSelected(accountId);
    this.syncSelection(false);
  }

  async loadAccounts(): Promise<void> {
    this.accountsRequested = true;
    try {
      const response = await tradingApi.listAccounts();
      this.allAccounts = response.accounts;
      this.patch({
        plannedKinds: response.plannedKinds,
        unavailable: false,
        ...(this.accountsFailed ? { error: null } : {}),
      });
      this.accountsFailed = false;
      this.syncSelection(false);
    } catch (cause) {
      this.accountsRequested = false;
      this.accountsFailed = true;
      if (cause instanceof ApiError && cause.status === 503) this.patch({ unavailable: true });
      else this.patch({ error: tradingErrorMessage(cause) });
      // Chart overlays keep the store retained for the page's lifetime, so a
      // load that failed while the backend was starting must retry by itself.
      if (!(cause instanceof ApiError) || cause.status >= 500) this.scheduleAccountsRetry();
    }
  }

  async createAccount(body: Record<string, unknown>): Promise<TradingAccount> {
    const account = await tradingApi.createAccount(body);
    await this.loadAccounts();
    this.select(account.id);
    return account;
  }

  async refresh(): Promise<void> {
    await this.data?.refreshAfterPending();
  }

  async refreshJournal(): Promise<void> {
    // The pool shares this refresh with every chart using the account.
    await this.data?.refreshAfterPending();
  }

  clearError(): void {
    this.data?.clearError();
    this.patch({ error: null });
  }

  reportError(cause: unknown): void {
    this.patch({ error: tradingErrorMessage(cause) });
  }

  private patch(next: Partial<TradingAccountsState>): void {
    this.state = { ...this.state, ...next };
    for (const listener of this.listeners) listener();
  }

  /**
   * Resolves the effective account; reloads its data when it changed or when
   * the first consumer arrives after a pause (the cached copy may be stale).
   */
  private syncSelection(firstConsumer: boolean): void {
    const accounts = this.allAccounts.filter((account) => !account.archived);
    const selected = accounts.find((account) => account.id === this.selectedId) ?? accounts[0] ?? null;
    const nextId = selected?.id ?? null;
    const changed = nextId !== this.dataAccountId;
    this.patch({ accounts, selected });
    if (!changed && !firstConsumer) return;
    this.stopPolling();
    this.dataAccountId = nextId;
    this.patch({ summary: null, trades: [], entries: [], loading: false, error: null });
    if (nextId === null || this.consumers === 0) return;
    const data = tradingAccountDataPool.account(nextId);
    this.data = data;
    const syncData = () => {
      if (this.data !== data || this.dataAccountId !== nextId) return;
      const { summary, trades, entries, loading, error } = data.getSnapshot();
      this.patch({ summary, trades, entries, loading, error });
    };
    this.unsubscribeData = data.subscribe(syncData);
    this.releaseData = data.retain();
    syncData();
  }

  private scheduleAccountsRetry(): void {
    if (this.accountsRetry !== null || this.consumers === 0) return;
    this.accountsRetry = setTimeout(() => {
      this.accountsRetry = null;
      if (this.consumers > 0 && !this.accountsRequested) void this.loadAccounts();
    }, ACCOUNTS_RETRY_MS);
  }

  private stopPolling(): void {
    this.unsubscribeData?.();
    this.unsubscribeData = null;
    this.releaseData?.();
    this.releaseData = null;
    this.data = null;
    if (this.consumers === 0 && this.accountsRetry !== null) {
      clearTimeout(this.accountsRetry);
      this.accountsRetry = null;
    }
  }

}

export const tradingAccountsStore = new TradingAccountsStore();
