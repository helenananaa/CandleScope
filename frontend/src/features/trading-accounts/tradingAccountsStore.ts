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

function isActive(summary: AccountSummary | null): boolean {
  return summary !== null
    && summary.account.kind === "practice"
    && (summary.positions.length > 0 || summary.workingOrders.length > 0);
}

/**
 * One copy of the selected account's data for the whole window: the rail
 * panel and every chart cell's overlay read it, and polling runs once while
 * any of them is retained.
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
  private controller: AbortController | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;

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
    const accountId = this.dataAccountId;
    if (accountId === null) return;
    this.patch({ loading: true });
    try {
      await Promise.all([this.loadAccountData(accountId), this.refreshJournal()]);
      if (this.dataAccountId === accountId) this.patch({ error: null });
    } catch (cause) {
      // An account switch or the last consumer leaving aborts requests; not an error.
      const aborted = cause instanceof DOMException && cause.name === "AbortError";
      if (!aborted && this.dataAccountId === accountId) this.patch({ error: tradingErrorMessage(cause) });
    } finally {
      if (this.dataAccountId === accountId) {
        this.patch({ loading: false });
        this.schedulePoll();
      }
    }
  }

  async refreshJournal(): Promise<void> {
    const accountId = this.dataAccountId;
    if (accountId === null) return;
    try {
      const response = await tradingApi.journal(accountId);
      if (this.dataAccountId === accountId) this.patch({ entries: response.entries });
    } catch (cause) {
      this.patch({ error: tradingErrorMessage(cause) });
    }
  }

  clearError(): void {
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
    if (changed) {
      this.controller?.abort();
      this.controller = null;
      this.dataAccountId = nextId;
      this.patch({ summary: null, trades: [], entries: [], loading: false });
    } else if (!firstConsumer) {
      return;
    }
    this.stopPolling();
    if (nextId !== null && this.consumers > 0) void this.refresh();
  }

  private async loadAccountData(accountId: string): Promise<void> {
    this.controller ??= new AbortController();
    const signal = this.controller.signal;
    const [summary, trades] = await Promise.all([
      tradingApi.summary(accountId, signal),
      tradingApi.trades(accountId, signal),
    ]);
    if (this.dataAccountId !== accountId) return;
    this.patch({ summary, trades: trades.trades });
  }

  private schedulePoll(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
    const accountId = this.dataAccountId;
    if (accountId === null || this.consumers === 0) return;
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.loadAccountData(accountId)
        .catch(() => undefined)
        .finally(() => {
          if (this.dataAccountId === accountId) this.schedulePoll();
        });
    }, isActive(this.state.summary) ? ACTIVE_POLL_MS : IDLE_POLL_MS);
  }

  private scheduleAccountsRetry(): void {
    if (this.accountsRetry !== null || this.consumers === 0) return;
    this.accountsRetry = setTimeout(() => {
      this.accountsRetry = null;
      if (this.consumers > 0 && !this.accountsRequested) void this.loadAccounts();
    }, ACCOUNTS_RETRY_MS);
  }

  private stopPolling(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
    if (this.consumers === 0) {
      this.controller?.abort();
      this.controller = null;
      if (this.accountsRetry !== null) clearTimeout(this.accountsRetry);
      this.accountsRetry = null;
    }
  }
}

export const tradingAccountsStore = new TradingAccountsStore();
