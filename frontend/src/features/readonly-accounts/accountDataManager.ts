import { AccountApiError, type AccountStatus } from "./accountApi.js";
import { streamAccountState } from "./accountStateStream.js";

type Observer = { update: (state: AccountStatus) => void; error: (code: string) => void };
/** One private account connection per lifecycle owner, independent of market feeds. */
export class ReadOnlyAccountDataManager {
  private readonly observers = new Set<Observer>();
  private controller: AbortController | null = null;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private latest: AccountStatus | null = null;
  private closed = false;
  private retries = 0;
  constructor(private readonly transport = streamAccountState, private readonly retryMs = 2000) {}

  subscribe(update: Observer["update"], error: Observer["error"]): () => void {
    if (this.closed) throw new AccountApiError("ACCOUNT_MANAGER_CLOSED");
    if (this.observers.size >= 32) throw new AccountApiError("ACCOUNT_SUBSCRIPTION_CAPACITY");
    const observer = { update, error };
    this.observers.add(observer);
    if (this.latest) this.deliver(observer, this.latest);
    if (!this.controller && this.timer === undefined) this.connect();
    return () => {
      this.observers.delete(observer);
      if (!this.observers.size) this.stop();
    };
  }
  private deliver(observer: Observer, value: AccountStatus): void {
    try { observer.update(value); } catch { console.error("Account snapshot observer failed"); }
  }
  private connect(): void {
    if (this.closed || !this.observers.size) return;
    const controller = new AbortController(); this.controller = controller;
    void this.transport(controller.signal, (value) => {
      if (this.controller !== controller || controller.signal.aborted) return;
      this.latest = value;
      for (const observer of [...this.observers]) if (this.observers.has(observer)) this.deliver(observer, value);
    }).catch((failure: unknown) => {
      if (this.controller !== controller || controller.signal.aborted) return;
      const code = failure instanceof AccountApiError ? failure.code : "ACCOUNT_NETWORK_UNAVAILABLE";
      for (const observer of [...this.observers]) if (this.observers.has(observer)) { try { observer.error(code); } catch { console.error("Account error observer failed"); } }
    }).finally(() => {
      if (this.controller !== controller) return;
      this.controller = null;
      if (!controller.signal.aborted && !this.closed && this.observers.size) {
        this.retries++;
        this.timer = setTimeout(() => { this.timer = undefined; this.connect(); }, this.retryMs);
      }
    });
  }
  private stop(): void {
    const controller = this.controller; this.controller = null;
    controller?.abort(); clearTimeout(this.timer); this.timer = undefined; this.latest = null;
  }
  diagnostics() { return { closed: this.closed, subscriptions: this.observers.size, connections: this.controller ? 1 : 0, retries: this.retries }; }
  dispose(): void { this.closed = true; this.observers.clear(); this.stop(); }
}
