import { tradingApi } from "./tradingApi.js";
import { tradingErrorMessage } from "./tradingErrors.js";
import type { AccountSummary, JournalEntry, Trade } from "./tradingTypes.js";

type ReadApi = Pick<typeof tradingApi, "summary" | "trades" | "journal"> & Partial<Pick<typeof tradingApi, "stateStream">>;
export interface TradingAccountDataState {
  accountId: string;
  summary: AccountSummary | null;
  trades: Trade[];
  entries: JournalEntry[];
  loading: boolean;
  error: string | null;
}

function empty(accountId: string): TradingAccountDataState {
  return { accountId, summary: null, trades: [], entries: [], loading: false, error: null };
}

/** One read owner for each account, shared by the panel and pinned chart views. */
export class TradingAccountData {
  private state: TradingAccountDataState;
  private readonly listeners = new Set<() => void>();
  private consumers = 0;
  private generation = 0;
  private controller: AbortController | null = null;
  private pending: Promise<void> | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private finishFirst: (() => void) | null = null;

  constructor(readonly accountId: string, private readonly api: ReadApi) {
    this.state = empty(accountId);
  }

  getSnapshot = (): TradingAccountDataState => this.state;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  retain(): () => void {
    this.consumers++;
    if (this.consumers === 1) void this.refresh();
    let released = false;
    return () => {
      if (released) return;
      released = true;
      if (--this.consumers !== 0) return;
      this.generation++;
      this.finishFirst?.();
      this.controller?.abort();
      this.controller = null;
      this.pending = null;
      if (this.timer !== null) clearTimeout(this.timer);
      this.timer = null;
      // Retain the small observer identity, not unbounded inactive trade data.
      this.publish(empty(this.accountId));
    };
  }

  clearError(): void { this.publish({ ...this.state, error: null }); }

  /** A completed write must be followed by a read started after that write. */
  async refreshAfterPending(): Promise<void> {
    const generation = this.generation;
    if (this.pending !== null) {
      await this.pending;
      if (this.consumers === 0) return;
      if (generation !== this.generation) {
        await this.pending;
        return;
      }
    }
    await this.refresh();
  }

  refresh(): Promise<void> {
    if (this.api.stateStream) return this.refreshStream();
    if (this.pending !== null) return this.pending;
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
    const generation = ++this.generation;
    const controller = new AbortController();
    this.controller = controller;
    this.publish({ ...this.state, loading: true, error: null });
    // Defer API calls so a synchronously throwing transport is also contained.
    const pending = Promise.resolve().then(async () => {
      if (controller.signal.aborted) return;
      try {
        const current = () => generation === this.generation && !controller.signal.aborted;
        // A journal outage must not block current positions/fills in the panel.
        // Both read groups still share this owner's cancellation and poll cycle.
        const readTrading = async () => {
          const [summary, trades] = await Promise.all([
            this.api.summary(this.accountId, controller.signal),
            this.api.trades(this.accountId, controller.signal),
          ]);
          if (!current()) return;
          if (summary.account.id !== this.accountId
            || summary.positions.some(position => position.accountId !== this.accountId)
            || summary.workingOrders.some(order => order.accountId !== this.accountId)
            || trades.trades.some(trade => trade.accountId !== this.accountId)) {
            throw new Error("Trading account response does not match its read owner");
          }
          this.publish({ ...this.state, summary, trades: trades.trades });
        };
        const readJournal = async () => {
          const journal = await this.api.journal(this.accountId, controller.signal);
          if (!current()) return;
          if (journal.entries.some(entry => entry.accountId !== this.accountId)) {
            throw new Error("Trading journal response does not match its read owner");
          }
          this.publish({ ...this.state, entries: journal.entries });
        };
        const results = await Promise.allSettled([readTrading(), readJournal()]);
        if (generation !== this.generation || controller.signal.aborted) return;
        const failures = results.filter(result => result.status === "rejected")
          .map(result => tradingErrorMessage(result.reason));
        this.publish({ ...this.state, loading: false, error: [...new Set(failures)].join("; ") || null });
      } catch (error) {
        if (generation !== this.generation || controller.signal.aborted) return;
        this.publish({ ...this.state, loading: false,
          error: tradingErrorMessage(error) });
      } finally {
        if (generation === this.generation) {
          this.pending = null;
          this.controller = null;
          this.schedulePoll();
        }
      }
    });
    this.pending = pending;
    return pending;
  }

  private refreshStream(): Promise<void> {
    if (this.consumers === 0) return Promise.resolve();
    this.finishFirst?.();
    this.controller?.abort();
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
    const generation = ++this.generation;
    const controller = new AbortController(); this.controller = controller;
    const current = () => generation === this.generation && !controller.signal.aborted;
    this.publish({ ...this.state, loading: true, error: null });
    let resolve!: () => void;
    const first = new Promise<void>(done => { resolve = done; });
    const finish = () => {
      resolve();
      if (this.finishFirst === finish) this.finishFirst = null;
      if (this.pending === first) this.pending = null;
    };
    this.pending = first; this.finishFirst = finish;
    void Promise.resolve().then(() => this.api.stateStream!(this.accountId, controller.signal, value => {
      if (!current()) return;
      this.publish({ ...this.state, summary: value.summary, trades: value.trades,
        entries: value.entries ?? this.state.entries, loading: false, error: value.journalError ?? null });
      // Manual accounts do not own practice market leases. Preserve their
      // existing quote revalidation until they have a live valuation source.
      if (value.summary.account.kind === "manual" && this.timer === null) {
        this.timer = setTimeout(() => { this.timer = null; void this.refresh(); }, 15_000);
      }
      finish();
    })).catch((error: unknown) => {
      if (current()) this.publish({ ...this.state, loading: false, error: tradingErrorMessage(error) });
    }).finally(() => {
      finish();
      if (generation === this.generation) {
        this.controller = null;
        this.schedulePoll();
      }
    });
    return first;
  }

  private publish(state: TradingAccountDataState): void {
    this.state = state;
    for (const listener of this.listeners) {
      try { listener(); } catch { console.error("Trading account observer failed"); }
    }
  }

  private schedulePoll(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
    if (this.consumers === 0) return;
    if (this.api.stateStream) {
      this.timer = setTimeout(() => { this.timer = null; void this.refresh(); }, 2_000);
      return;
    }
    const summary = this.state.summary;
    const active = summary?.account.kind === "practice"
      && (summary.positions.length > 0 || summary.workingOrders.length > 0);
    this.timer = setTimeout(() => { this.timer = null; void this.refresh(); }, active ? 2_000 : 15_000);
  }
}

export class TradingAccountDataPool {
  private readonly accounts = new Map<string, TradingAccountData>();
  constructor(private readonly api: ReadApi = tradingApi) {}
  account(accountId: string): TradingAccountData {
    let data = this.accounts.get(accountId);
    if (!data) {
      data = new TradingAccountData(accountId, this.api);
      this.accounts.set(accountId, data);
    }
    return data;
  }
}

export const tradingAccountDataPool = new TradingAccountDataPool();
