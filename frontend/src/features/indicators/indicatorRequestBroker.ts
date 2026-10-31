/** Exact semantic serialization: never use a lossy digest as an equality proof. */
export function indicatorRequestKey(value: unknown): string {
  return JSON.stringify(value, (_key, item: unknown) => item && typeof item === "object" && !Array.isArray(item)
    ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b))) : item);
}

const aborted = () => new DOMException("Indicator demand no longer current", "AbortError");
interface Consumer<P> { resolve(payload: P): void; reject(error: unknown): void; cleanup(): void }
interface Entry<R, P> {
  key: string;
  group: string;
  request: R;
  current(): boolean;
  consumers: Set<Consumer<P>>;
  priority: number;
  batch: Batch<R, P> | null;
  settled: boolean;
}
interface Batch<R, P> { entries: Entry<R, P>[]; controller: AbortController }

export interface IndicatorRequestBrokerOptions<R, P> {
  send(requests: R[], signal: AbortSignal, publish: (index: number, payload: P) => void): Promise<P[]>;
  maxConcurrent?: number;
  maxPending?: number;
  coalesceMs?: number;
}

/** Workspace-owned in-flight work only. Results remain in the existing result
 * cache. A chart owns a consumer, never the physical batch's cancellation. */
export class IndicatorRequestBroker<R, P> {
  private readonly entries = new Map<string, Entry<R, P>>();
  private readonly batches = new Set<Batch<R, P>>();
  private timer: ReturnType<typeof setTimeout> | null = null;
  private disposed = false;
  private joined = 0;
  private physical = 0;
  private completed = 0;
  constructor(private readonly options: IndicatorRequestBrokerOptions<R, P>) {}

  request(input: { key: string; group: string; request: R; current(): boolean; signal?: AbortSignal | undefined; speculative?: boolean }): Promise<P> {
    if (this.disposed || input.signal?.aborted) return Promise.reject(aborted());
    let entry = this.entries.get(input.key);
    if (entry && !entry.current()) { this.finish(entry, undefined, aborted()); entry = undefined; }
    if (!entry) {
      if (!input.current()) return Promise.reject(aborted());
      if (this.entries.size >= (this.options.maxPending ?? 128)) return Promise.reject(new Error("Indicator request budget exceeded"));
      entry = { key: input.key, group: input.group, request: structuredClone(input.request), current: input.current,
        consumers: new Set(), priority: input.speculative ? 1 : 0, batch: null, settled: false };
      this.entries.set(entry.key, entry);
    } else { this.joined += 1; if (!input.speculative) entry.priority = 0; }
    const target = entry;
    const result = new Promise<P>((resolve, reject) => {
      const onAbort = () => {
        target.consumers.delete(consumer); consumer.cleanup(); reject(aborted());
        if (!target.consumers.size) this.finish(target, undefined, aborted());
      };
      const consumer: Consumer<P> = { resolve, reject, cleanup: () => input.signal?.removeEventListener("abort", onAbort) };
      target.consumers.add(consumer);
      input.signal?.addEventListener("abort", onAbort, { once: true });
    });
    this.schedule();
    return result;
  }

  diagnostics() {
    return { pending: this.entries.size, physicalActive: this.batches.size, joined: this.joined,
      totalPhysical: this.physical, completed: this.completed,
      consumers: [...this.entries.values()].reduce((sum, entry) => sum + entry.consumers.size, 0) };
  }

  dispose(): void {
    this.disposed = true;
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
    for (const entry of [...this.entries.values()]) this.finish(entry, undefined, aborted());
    for (const batch of this.batches) batch.controller.abort();
  }

  private finish(entry: Entry<R, P>, payload?: P, error?: unknown): void {
    if (entry.settled) return;
    entry.settled = true;
    if (this.entries.get(entry.key) === entry) this.entries.delete(entry.key);
    const failure = error ?? (!entry.current() ? aborted() : undefined);
    for (const consumer of entry.consumers) {
      consumer.cleanup();
      if (failure !== undefined) consumer.reject(failure);
      else consumer.resolve(payload!);
    }
    entry.consumers.clear();
    if (failure !== undefined && entry.batch?.entries.every(item => item.settled)) entry.batch.controller.abort();
  }

  private schedule(): void {
    if (this.disposed || this.timer !== null || ![...this.entries.values()].some(entry => !entry.batch)) return;
    this.timer = setTimeout(() => { this.timer = null; this.flush(); }, this.options.coalesceMs ?? 40);
  }

  private flush(): void {
    if (this.disposed) return;
    const queued = [...this.entries.values()].filter(entry => !entry.batch).sort((a, b) => a.priority - b.priority);
    while (queued.length && this.batches.size < (this.options.maxConcurrent ?? 2)) {
      const first = queued.shift()!;
      const entries = [first];
      for (let index = 0; index < queued.length && entries.length < 32;) {
        if (queued[index]!.group === first.group) entries.push(...queued.splice(index, 1)); else index += 1;
      }
      const live = entries.filter(entry => {
        if (entry.current()) return true;
        this.finish(entry, undefined, aborted()); return false;
      });
      if (!live.length) continue;
      const batch = { entries: live, controller: new AbortController() };
      for (const entry of live) entry.batch = batch;
      this.batches.add(batch); this.physical += 1;
      const publish = (index: number, payload: P) => {
        const entry = live[index];
        if (entry) this.finish(entry, payload);
      };
      void Promise.resolve().then(() => this.options.send(live.map(entry => entry.request), batch.controller.signal, publish)).then(results => {
        if (results.length !== live.length) throw new Error("Indicator batch result count mismatch");
        results.forEach((payload, index) => publish(index, payload)); this.completed += 1;
      }).catch(error => { for (const entry of live) this.finish(entry, undefined, error); })
        .finally(() => { this.batches.delete(batch); this.schedule(); });
    }
  }
}
