import { API_BASE, httpBaseToWsBase } from "../../../services/apiConfig.js";
import { adoptSynthetic, EMPTY_SYNTHETIC, type SyntheticRequest, type SyntheticSnapshot } from "./syntheticSeries.js";

export interface SyntheticSocket {
  onopen: (() => void) | null;
  onmessage: ((event: { data: string }) => void) | null;
  onclose: (() => void) | null;
  onerror: (() => void) | null;
  send(value: string): void;
  close(): void;
}
interface Entry {
  request: SyntheticRequest;
  state: SyntheticSnapshot;
  socket: SyntheticSocket | null;
  timer: ReturnType<typeof setTimeout> | null;
  listeners: Set<() => void>;
  attempts: number;
  closed: boolean;
}
export interface SyntheticView {
  getSnapshot(): SyntheticSnapshot;
  subscribe(listener: () => void): () => void;
  release(): void;
}

/** Shared immutable backend replica. Charts own separate display windows. */
export class SyntheticSeriesManager {
  private entries = new Map<string, Entry>();
  constructor(private socketFactory: () => SyntheticSocket = () =>
    new WebSocket(`${httpBaseToWsBase(API_BASE)}/synthetic/stream`) as unknown as SyntheticSocket) {}

  acquire(request: SyntheticRequest): SyntheticView {
    const key = JSON.stringify(request);
    let entry = this.entries.get(key);
    if (!entry) {
      if (this.entries.size >= 32) throw new Error("Synthetic subscription budget exceeded");
      entry = { request, state: EMPTY_SYNTHETIC, socket: null, timer: null, listeners: new Set(), attempts: 0, closed: false };
      this.entries.set(key, entry);
    }
    const target = entry;
    const leaseListeners = new Set<() => void>();
    let released = false;
    // A lease exists even before its first listener subscribes.
    const hold = () => {};
    target.listeners.add(hold);
    if (!target.socket && !target.timer) this.connect(target);
    return {
      getSnapshot: () => target.state,
      subscribe: listener => {
        if (released) return () => {};
        leaseListeners.add(listener); target.listeners.add(listener);
        return () => { leaseListeners.delete(listener); target.listeners.delete(listener); };
      },
      release: () => {
        if (released) return;
        released = true;
        for (const listener of leaseListeners) target.listeners.delete(listener);
        target.listeners.delete(hold);
        if (!target.listeners.size) {
          target.closed = true;
          if (target.timer) clearTimeout(target.timer);
          target.socket?.close();
          this.entries.delete(key);
        }
      },
    };
  }

  private publish(entry: Entry, state: SyntheticSnapshot) {
    entry.state = state;
    for (const listener of [...entry.listeners]) listener();
  }
  private connect(entry: Entry) {
    if (entry.closed) return;
    let socket: SyntheticSocket;
    try { socket = this.socketFactory(); }
    catch (error) { this.recover(entry, String(error)); return; }
    entry.socket = socket;
    const current = () => !entry.closed && entry.socket === socket;
    let first = true;
    socket.onopen = () => { if (current()) socket.send(JSON.stringify(entry.request)); };
    socket.onmessage = event => {
      if (!current() || event.data === "pong") return;
      try {
        const message: unknown = JSON.parse(event.data);
        const previous = first ? EMPTY_SYNTHETIC : entry.state;
        const state = adoptSynthetic(previous, message, entry.request);
        if (first && (message as { type?: string }).type !== "snapshot") throw new Error("Synthetic snapshot required");
        const totalRows = [...this.entries.values()].reduce((sum, other) => sum + (other === entry ? 0 : other.state.rows.length), 0);
        if (totalRows + state.rows.length > 20_000) throw new Error("Shared synthetic cache budget exceeded");
        first = false;
        entry.attempts = 0;
        this.publish(entry, state);
        if (state.status !== "ready") this.recover(entry, state.reason ?? "Synthetic series unavailable");
      } catch (error) {
        this.recover(entry, error instanceof Error ? error.message : String(error));
      }
    };
    socket.onclose = () => { if (current()) this.recover(entry, "Synthetic connection interrupted"); };
    socket.onerror = () => { if (current()) this.recover(entry, "Synthetic connection interrupted"); };
  }
  private recover(entry: Entry, reason: string) {
    const socket = entry.socket;
    entry.socket = null;
    socket?.close();
    if (entry.closed || entry.timer) return;
    this.publish(entry, Object.freeze({ ...entry.state, status: "stale", reason }));
    entry.timer = setTimeout(() => {
      entry.timer = null;
      this.connect(entry);
    }, Math.min(10_000, 500 * 2 ** Math.min(entry.attempts++, 5)));
  }
  diagnostics() {
    return { sharedSeries: this.entries.size, retainedRows: [...this.entries.values()].reduce((sum, entry) => sum + entry.state.rows.length, 0) };
  }
  closeAll() {
    for (const entry of this.entries.values()) {
      entry.closed = true;
      if (entry.timer) clearTimeout(entry.timer);
      entry.socket?.close();
    }
    this.entries.clear();
  }
}
