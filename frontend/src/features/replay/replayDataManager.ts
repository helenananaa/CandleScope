import { SeriesWindowStore } from "../market-data/window/seriesWindowStore.js";

export interface ReplaySequenceIdentity {
  readonly runId: string;
  readonly trackId: string;
  readonly sessionId: string;
  readonly dataEpoch: string;
  readonly generation: number;
  readonly interval: string;
}

const abortError = () => new DOMException("Replay demand released or superseded", "AbortError");

export interface ReplayOperationIdentity {
  readonly runId: string;
  readonly sessionId?: string;
  readonly purpose: "run-entry" | "viewer" | "adapter";
}
type ReplayDemandIdentity = ReplaySequenceIdentity | ReplayOperationIdentity;

/** A replay-only namespace. Its mutable display windows never enter the live
 * market cache, and equal markets/periods never imply shared navigation state. */
export class ReplayDataManager {
  private readonly active = new Set<ReplayDemandLease>();
  private closed = false;
  private nextOwner = 0;
  createSequence(): ReplaySequenceLease {
    if (this.closed) throw new Error("Replay data manager closed");
    return new ReplaySequenceLease(`replay-window-${++this.nextOwner}`, this);
  }
  createOperations(identity: ReplayOperationIdentity): ReplayOperationLease {
    if (this.closed) throw new Error("Replay data manager closed");
    return new ReplayOperationLease(`replay-operation-${++this.nextOwner}`, this, identity);
  }
  activate(lease: ReplayDemandLease): void {
    if (this.closed) throw new Error("Replay data manager closed");
    this.active.add(lease);
  }
  deactivate(lease: ReplayDemandLease): void { this.active.delete(lease); }
  diagnostics() {
    const sequences = [...this.active].filter(lease => lease.kind === "sequence").map(lease => lease.diagnostics());
    const operations = [...this.active].filter(lease => lease.kind === "operation").map(lease => lease.diagnostics());
    return { sequences, operations, activeSequences: sequences.length, activeOperations: operations.length,
      requests: [...sequences, ...operations].reduce((sum, item) => sum + item.requests, 0),
      streams: operations.reduce((sum, item) => sum + item.streams, 0),
      bars: sequences.reduce((sum, item) => sum + item.bars, 0) };
  }
  dispose(): void {
    this.closed = true;
    for (const lease of this.active) lease.close();
  }
}

/** Construction is inert so an abandoned React render cannot retain resources. */
class ReplayDemandLease {
  private identity: Readonly<ReplayDemandIdentity> | null = null;
  private identityKey = "";
  private epoch = 0;
  private consumers = 0;
  private totalRequests = 0;
  private retentionEpoch = 0;
  private readonly requests = new Set<AbortController>();
  private readonly resources = new Set<() => void>();
  private cleanupErrors = 0;
  constructor(readonly owner: string, private readonly manager: ReplayDataManager,
    readonly kind: "sequence" | "operation") {}
  get active(): boolean { return this.consumers > 0; }

  protected bindIdentity(identity: ReplayDemandIdentity, key: string): boolean {
    if (key === this.identityKey) return false;
    this.cancel();
    this.identity = Object.freeze({ ...identity });
    this.identityKey = key;
    return true;
  }
  retain(): () => void {
    this.manager.activate(this);
    this.consumers += 1;
    const retentionEpoch = this.retentionEpoch;
    let released = false;
    return () => {
      if (released) return;
      released = true;
      if (retentionEpoch === this.retentionEpoch && this.consumers > 0 && --this.consumers === 0) this.close();
    };
  }
  request<T>(load: (signal: AbortSignal) => Promise<T>, signal?: AbortSignal): Promise<T> {
    if (!this.consumers || !this.identity || signal?.aborted) return Promise.reject(abortError());
    const epoch = this.epoch, controller = new AbortController();
    this.totalRequests += 1;
    const cancel = () => controller.abort();
    signal?.addEventListener("abort", cancel, { once: true });
    this.requests.add(controller);
    let removeAbortListener = () => {};
    return new Promise<T>((resolve, reject) => {
      const aborted = () => reject(abortError());
      controller.signal.addEventListener("abort", aborted, { once: true });
      removeAbortListener = () => controller.signal.removeEventListener("abort", aborted);
      let pending: Promise<T>;
      try { pending = load(controller.signal); } catch (error) {
        pending = Promise.reject(error instanceof Error ? error : new Error(String(error)));
      }
      pending.then(value => {
        if (!this.consumers || epoch !== this.epoch || controller.signal.aborted) reject(abortError());
        else resolve(value);
      }, reject);
    }).finally(() => {
      removeAbortListener();
      signal?.removeEventListener("abort", cancel);
      this.requests.delete(controller);
    });
  }
  /** Register before start() can synchronously deliver a frame. Every callback
   * uses the resource fence, so stop/reopen within one lease rejects old frames. */
  openResource<T>(create: (current: () => boolean) => T, dispose: (value: T) => void): { value: T; release(): void; current(): boolean } {
    if (!this.active || !this.identity) throw abortError();
    const epoch = this.epoch;
    let released = false;
    const current = () => !released && this.active && epoch === this.epoch;
    const value = create(current);
    const release = () => {
      if (released) return;
      released = true;
      this.resources.delete(release);
      try { dispose(value); } catch { this.cleanupErrors += 1; }
    };
    if (!current()) { release(); throw abortError(); }
    this.resources.add(release);
    return { value, release, current };
  }
  close(): void {
    this.consumers = 0;
    this.retentionEpoch += 1;
    this.cancel();
    this.manager.deactivate(this);
  }
  diagnostics() { return { owner: this.owner, identity: this.identity, consumers: this.consumers,
    bars: 0, requests: this.requests.size, totalRequests: this.totalRequests,
    streams: this.resources.size, cleanupErrors: this.cleanupErrors }; }
  private cancel(): void {
    this.epoch += 1;
    for (const request of this.requests) request.abort();
    this.requests.clear();
    for (const release of this.resources) release();
  }
}

export class ReplaySequenceLease extends ReplayDemandLease {
  readonly store = new SeriesWindowStore();
  constructor(owner: string, manager: ReplayDataManager) { super(owner, manager, "sequence"); }
  bind(identity: ReplaySequenceIdentity): void {
    if (this.bindIdentity(identity, JSON.stringify([identity.runId, identity.trackId, identity.sessionId,
      identity.dataEpoch, identity.generation, identity.interval]))) this.store.clear({ source: "replay-manager-identity-change" });
  }
  override diagnostics() { return { ...super.diagnostics(), bars: this.store.barCount }; }
}

/** Run/session HTTP and stream ownership; never stores account data or rows. */
export class ReplayOperationLease extends ReplayDemandLease {
  constructor(owner: string, manager: ReplayDataManager, identity: ReplayOperationIdentity) {
    super(owner, manager, "operation");
    this.bindIdentity(identity, JSON.stringify([identity.runId, identity.sessionId, identity.purpose]));
  }
}
