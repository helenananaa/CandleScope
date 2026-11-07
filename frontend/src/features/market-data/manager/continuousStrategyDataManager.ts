import { StrategyRunStreamError } from "../../backtest/backtestRunStream.js";
import { ContinuousViewReducer, type ContinuousView } from "../../backtest/continuous/continuousView.js";
import { mergeRepair } from "../../backtest/continuous/continuousRepairView.js";
import type { CommittedIdentity, ContinuousApi, ContinuousCapabilities, ContinuousControl, ContinuousCreate,
  ContinuousCreation, ContinuousPage, ContinuousPacket, ContinuousRepair, ContinuousRepairConfirm, ResultKind } from "../../backtest/continuous/continuousTypes.js";

export interface ContinuousObservation {
  creation: ContinuousCreation | null; result: ContinuousView | null;
  initialReady: boolean; connection: "loading" | "connected" | "reconnecting" | "closed" | "error";
  error: Error | null;
  repair: ContinuousRepair | null;
}
type Operation = <T>(signal: AbortSignal | undefined, action: (signal: AbortSignal) => Promise<T>) => Promise<T>;
type Entry = { reducer: ContinuousViewReducer; listeners: Set<(state: ContinuousObservation) => void>;
  controller: AbortController; state: ContinuousObservation; done: boolean };

function wait(ms: number, signal: AbortSignal): Promise<void> {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const abort = () => { clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, ms);
    signal.addEventListener("abort", abort, { once: true });
  });
}

/** One shared view per run, isolated from chart Kline stores. Releasing the last
 * observer closes transport only; durable backend execution remains independent. */
export class ContinuousStrategyDataManager {
  private readonly entries = new Map<string, Entry>();
  private observers = 0;
  private closed = false;
  constructor(private readonly api: ContinuousApi, private readonly operation: Operation, private readonly retryDelay = wait) {}

  capabilities(signal?: AbortSignal): Promise<ContinuousCapabilities> { return this.operation(signal, (owned) => this.api.capabilities(owned)); }
  editorParameters(source: string, signal: AbortSignal) { return this.operation(signal, (owned) => this.api.editorParameters(source, owned)); }
  catalog(signal?: AbortSignal) { return this.operation(signal, (owned) => this.api.catalog(owned)); }
  create(key: string, body: ContinuousCreate, signal?: AbortSignal) { return this.operation(signal, (owned) => this.api.create(key, body, owned)); }
  request(key: string, signal?: AbortSignal) { return this.operation(signal, (owned) => this.api.request(key, owned)); }
  status(id: string, signal?: AbortSignal) { return this.operation(signal, (owned) => this.api.status(id, owned)); }
  control(key: string, body: ContinuousControl, signal?: AbortSignal) { return this.operation(signal, (owned) => this.api.control(key, body, owned)); }
  repairPreview(id: string, body: { expected: CommittedIdentity; resume_after: boolean }, signal?: AbortSignal) { return this.operation(signal, (owned) => this.api.repairPreview(id, body, owned)); }
  async repairStatus(key: string, signal?: AbortSignal) {
    const response = await this.operation(signal, (owned) => this.api.repairStatus(key, owned));
    const entry = this.entries.get(response.repair.run_id); if (entry) this.publishRepair(entry, response.repair);
    return response;
  }
  latestRepair(id: string, signal?: AbortSignal) { return this.operation(signal, (owned) => this.api.latestRepair(id, owned)); }
  async repair(id: string, key: string, body: ContinuousRepairConfirm, signal?: AbortSignal) {
    const response = await this.operation(signal, (owned) => this.api.repair(id, key, body, owned));
    const entry = this.entries.get(id); if (entry) this.publishRepair(entry, response.repair);
    return response;
  }
  async cancelRepair(key: string, expected: CommittedIdentity, signal?: AbortSignal) {
    const response = await this.operation(signal, (owned) => this.api.cancelRepair(key, expected, owned));
    const entry = this.entries.get(response.repair.run_id); if (entry) this.publishRepair(entry, response.repair);
    return response;
  }

  observe(id: string, accept: (state: ContinuousObservation) => void, creation: ContinuousCreation | null = null): () => void {
    if (this.closed) throw new StrategyRunStreamError("STRATEGY_MANAGER_CLOSED", "Strategy data manager is closed");
    if (this.observers >= 32) throw new StrategyRunStreamError("RUN_CAPACITY_EXCEEDED", "Strategy observer capacity reached");
    let entry = this.entries.get(id);
    if (!entry) {
      if (this.entries.size >= 4) throw new StrategyRunStreamError("RUN_CAPACITY_EXCEEDED", "Strategy result view capacity reached");
      entry = { reducer: new ContinuousViewReducer(id), listeners: new Set(), controller: new AbortController(), done: false,
        state: { creation, result: null, initialReady: false, connection: "loading", error: null, repair: null } };
      this.entries.set(id, entry);
      const owned = entry;
      void this.operation(entry.controller.signal, (signal) => this.follow(id, owned, signal)).catch((failure: unknown) => {
        if (!owned.controller.signal.aborted && !this.closed)
          this.publish(owned, { connection: "error", error: failure instanceof Error ? failure : new Error(String(failure)) });
      }).finally(() => { owned.done = true; });
    }
    const owned = entry;
    // A distinct wrapper allows the same callback to hold two independent leases.
    const listener = (state: ContinuousObservation) => accept(state);
    owned.listeners.add(listener); this.observers += 1;
    try { accept(owned.state); }
    catch (failure) { owned.listeners.delete(listener); this.observers -= 1; if (!owned.listeners.size) { owned.controller.abort(); this.entries.delete(id); } throw failure; }
    let released = false;
    return () => {
      if (released) return;
      released = true; if (owned.listeners.delete(listener)) this.observers -= 1;
      if (!owned.listeners.size) {
        owned.controller.abort(); owned.reducer.clear();
        if (this.entries.get(id) === owned) this.entries.delete(id);
      }
    };
  }

  private publish(entry: Entry, patch: Partial<ContinuousObservation>): void {
    if (entry.controller.signal.aborted || this.closed) return;
    entry.state = { ...entry.state, ...patch };
    for (const listener of entry.listeners) { try { listener(entry.state); } catch { /* Consumer errors cannot stop sibling views. */ } }
  }

  private publishRepair(entry: Entry, repair: ContinuousRepair | null | undefined): void {
    const next = mergeRepair(entry.state.repair, repair, entry.reducer.runId);
    if (next !== entry.state.repair) this.publish(entry, { repair: next });
  }

  private async initial(id: string, entry: Entry, signal: AbortSignal): Promise<void> {
    for (let attempt = 0; ; attempt += 1) {
      try {
        entry.reducer.reset();
        const initial = await this.api.initial(id, signal);
        signal.throwIfAborted();
        this.publish(entry, { creation: initial.creation, initialReady: false });
        let page = initial.result, begin = true, pages = 0;
        const cursors = new Set<string>();
        while (page) {
          const result = entry.reducer.accept(page, { snapshot: true, begin, complete: !page.more, after: 0 });
          if (result) this.publish(entry, { result, initialReady: initial.initial_result_ready });
          if (!page.more) break;
          const next = page.next_cursor;
          const cursor = JSON.stringify(next);
          if (!next || cursors.has(cursor) || ++pages > 2048) throw new StrategyRunStreamError("CONTINUOUS_VIEW_INVALID", "Invalid result page cursor");
          cursors.add(cursor);
          page = await this.api.page(id, { since_revision: 0, expected: page.identity, change_cursor: next }, signal);
          signal.throwIfAborted(); begin = false;
        }
        return;
      } catch (failure) {
        entry.reducer.reset();
        if (signal.aborted || !(failure instanceof StrategyRunStreamError) || failure.code !== "CONTINUOUS_COMMIT_CONFLICT" || attempt >= 3) throw failure;
        await this.retryDelay(100 * (attempt + 1), signal);
      }
    }
  }

  private packet(entry: Entry, packet: ContinuousPacket): void {
    if (packet.type === "connected") { this.publish(entry, { connection: "connected", error: null }); return; }
    if (packet.type === "heartbeat" || packet.type === "pong") return;
    if (packet.type === "reset") { entry.reducer.reset(); return; }
    if (packet.type === "snapshot" || packet.type === "update") {
      this.publishRepair(entry, packet.repair);
      const result = entry.reducer.accept(packet as ContinuousPage, { snapshot: packet.type === "snapshot",
        begin: packet.begin === true, complete: packet.complete === true, after: packet.after_checkpoint ?? -1 });
      if (result) this.publish(entry, { result, creation: packet.creation ?? entry.state.creation,
        initialReady: packet.initial_result_ready === true, connection: "connected", error: null });
    } else if (packet.type === "preparation" || packet.type === "initializing")
      this.publish(entry, { creation: packet.creation ?? entry.state.creation, initialReady: false, connection: "connected" });
    else throw new StrategyRunStreamError("PROTOCOL_UNSUPPORTED", "Unexpected continuous strategy event");
  }

  private async follow(id: string, entry: Entry, signal: AbortSignal): Promise<void> {
    const status = await this.api.status(id, signal);
    signal.throwIfAborted(); this.publish(entry, { creation: status.creation });
    this.publishRepair(entry, status.repair);
    await this.initial(id, entry, signal);
    let failures = 0;
    while (!signal.aborted) {
      try {
        await this.api.stream(id, entry.reducer.current?.identity, signal, (packet) => {
          signal.throwIfAborted(); this.packet(entry, packet);
          if (packet.type !== "connected") failures = 0;
        });
        this.publish(entry, { connection: "closed" }); return;
      } catch (failure) {
        entry.reducer.reset();
        if (signal.aborted) return;
        if (!(failure instanceof StrategyRunStreamError) || failure.code !== "CONTINUOUS_DISCONNECTED" || failures >= 5) throw failure;
        this.publish(entry, { connection: "reconnecting" });
        await this.retryDelay(Math.min(4000, 250 * 2 ** failures++), signal);
      }
    }
  }

  rows(id: string, kind: ResultKind, identity: CommittedIdentity, limit?: number): unknown[] {
    const entry = this.entries.get(id);
    if (!entry) throw new StrategyRunStreamError("CONTINUOUS_VIEW_UNAVAILABLE", "Strategy view is no longer observed");
    return entry.reducer.rows(kind, identity, limit);
  }
  diagnostics() { return { closed: this.closed, observers: this.observers, views: [...this.entries].map(([id, entry]) => ({ id, ...entry.reducer.diagnostics() })) }; }
  dispose(): void {
    this.closed = true;
    for (const entry of this.entries.values()) { entry.controller.abort(); entry.reducer.clear(); entry.listeners.clear(); }
    this.entries.clear();
    this.observers = 0;
  }
}
