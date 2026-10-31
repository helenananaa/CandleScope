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

/** A replay-only namespace. Its mutable display windows never enter the live
 * market cache, and equal markets/periods never imply shared navigation state. */
export class ReplayDataManager {
  private readonly active = new Set<ReplaySequenceLease>();
  private closed = false;
  private nextOwner = 0;
  createSequence(): ReplaySequenceLease {
    if (this.closed) throw new Error("Replay data manager closed");
    return new ReplaySequenceLease(`replay-window-${++this.nextOwner}`, this);
  }
  activate(lease: ReplaySequenceLease): void {
    if (this.closed) throw new Error("Replay data manager closed");
    this.active.add(lease);
  }
  deactivate(lease: ReplaySequenceLease): void { this.active.delete(lease); }
  diagnostics() {
    const sequences = [...this.active].map(lease => lease.diagnostics());
    return { sequences, activeSequences: sequences.length,
      requests: sequences.reduce((sum, item) => sum + item.requests, 0),
      bars: sequences.reduce((sum, item) => sum + item.bars, 0) };
  }
  dispose(): void {
    this.closed = true;
    for (const lease of this.active) lease.close();
  }
}

/** Construction is inert so an abandoned React render cannot retain resources. */
export class ReplaySequenceLease {
  readonly store = new SeriesWindowStore();
  private identity: Readonly<ReplaySequenceIdentity> | null = null;
  private identityKey = "";
  private epoch = 0;
  private consumers = 0;
  private totalRequests = 0;
  private retentionEpoch = 0;
  private readonly requests = new Set<AbortController>();
  constructor(readonly owner: string, private readonly manager: ReplayDataManager) {}
  get active(): boolean { return this.consumers > 0; }

  bind(identity: ReplaySequenceIdentity): void {
    const key = JSON.stringify([identity.runId, identity.trackId, identity.sessionId,
      identity.dataEpoch, identity.generation, identity.interval]);
    if (key === this.identityKey) return;
    this.cancel();
    this.identity = Object.freeze({ ...identity });
    this.identityKey = key;
    this.store.clear({ source: "replay-manager-identity-change" });
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
    return new Promise<T>((resolve, reject) => {
      const aborted = () => reject(abortError());
      controller.signal.addEventListener("abort", aborted, { once: true });
      let pending: Promise<T>;
      try { pending = load(controller.signal); } catch (error) {
        pending = Promise.reject(error instanceof Error ? error : new Error(String(error)));
      }
      pending.then(value => {
        if (!this.consumers || epoch !== this.epoch || controller.signal.aborted) reject(abortError());
        else resolve(value);
      }, reject).finally(() => controller.signal.removeEventListener("abort", aborted));
    }).finally(() => {
      signal?.removeEventListener("abort", cancel);
      this.requests.delete(controller);
    });
  }
  close(): void {
    this.consumers = 0;
    this.retentionEpoch += 1;
    this.cancel();
    this.manager.deactivate(this);
  }
  diagnostics() { return { owner: this.owner, identity: this.identity, consumers: this.consumers,
    bars: this.store.barCount, requests: this.requests.size, totalRequests: this.totalRequests }; }
  private cancel(): void {
    this.epoch += 1;
    for (const request of this.requests) request.abort();
    this.requests.clear();
  }
}
