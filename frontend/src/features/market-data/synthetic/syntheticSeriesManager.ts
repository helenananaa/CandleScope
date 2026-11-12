import { API_BASE, httpBaseToWsBase } from "../../../services/apiConfig.js";
import { adoptSynthetic, EMPTY_SYNTHETIC, type SyntheticRequest, type SyntheticRow, type SyntheticSnapshot, type SyntheticOrigin } from "./syntheticSeries.js";
import type { KlineBar } from "../marketDataTypes.js";

interface CaptureBody {
  source: SyntheticRequest["source"]; rows: Array<{ time: number; open: number; high: number; low: number; close: number; volume?: number; is_closed: boolean }>;
  scope: string; cutoff_ms: number;
}

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
  pendingRows: number;
  capture?: CaptureBody;
  preparation: AbortController | null;
}
export interface SyntheticView {
  getRequest(): SyntheticRequest;
  getSnapshot(): SyntheticSnapshot;
  subscribe(listener: () => void): () => void;
  release(): void;
}

/** Shared immutable backend replica. Charts own separate display windows. */
export class SyntheticSeriesManager {
  private entries = new Map<string, Entry>();
  private generation = 0;
  constructor(private socketFactory: () => SyntheticSocket = () =>
    new WebSocket(`${httpBaseToWsBase(API_BASE)}/synthetic/stream`) as unknown as SyntheticSocket,
    private fetcher: typeof fetch = (...args) => fetch(...args)) {}

  private async registerCapture(body: CaptureBody, signal: AbortSignal) {
    const response = await this.fetcher(`${API_BASE}/synthetic/captures`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal,
    });
    if (!response.ok) throw new Error(`Captured synthetic source unavailable (${response.status})`);
    const result = await response.json() as Record<string, unknown>;
    if (result["kind"] !== "CAPTURED_WINDOW" || result["cutoff_ms"] !== body.cutoff_ms
      || typeof result["capture_id"] !== "string" || !/^[a-f0-9]{64}$/.test(result["capture_id"])) throw new Error("Invalid captured source receipt");
    return result as unknown as Extract<SyntheticOrigin, { kind: "CAPTURED_WINDOW" }>;
  }

  async acquireCaptured(request: SyntheticRequest, rows: readonly KlineBar[], scope: string, cutoff_ms: number, signal: AbortSignal) {
    const generation = this.generation;
    const body: CaptureBody = { source: request.source, scope, cutoff_ms, rows: rows.map(row => ({
      time: row.time, open: Number(row.open), high: Number(row.high), low: Number(row.low), close: Number(row.close),
      ...(row.volume == null ? {} : { volume: Number(row.volume) }), is_closed: row.is_closed !== false,
    })) };
    const origin = await this.registerCapture(body, signal);
    signal.throwIfAborted();
    if (generation !== this.generation) throw new DOMException("Synthetic owner changed", "AbortError");
    return this.acquire({ ...request, origin }, body);
  }

  acquire(request: SyntheticRequest, capture?: CaptureBody): SyntheticView {
    const key = JSON.stringify(request);
    let entry = this.entries.get(key);
    if (!entry) {
      if (this.entries.size >= 32) throw new Error("Synthetic subscription budget exceeded");
      entry = { request, state: EMPTY_SYNTHETIC, socket: null, timer: null, listeners: new Set(), attempts: 0, closed: false, pendingRows: 0,
        preparation: null, ...(capture ? { capture } : {}) };
      this.entries.set(key, entry);
      try { this.checkRows(); } catch (error) { this.entries.delete(key); throw error; }
    }
    const target = entry;
    const leaseListeners = new Set<() => void>();
    let released = false;
    // A lease exists even before its first listener subscribes.
    const hold = () => {};
    target.listeners.add(hold);
    if (!target.socket && !target.timer && !target.preparation) this.connect(target, Boolean(capture));
    return {
      getRequest: () => target.request,
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
          target.preparation?.abort();
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
  private connect(entry: Entry, registered = false) {
    if (entry.closed) return;
    if (entry.capture && !registered) {
      const controller = new AbortController(); entry.preparation = controller;
      void this.registerCapture(entry.capture, controller.signal).then(origin => {
        if (controller.signal.aborted || entry.closed) return;
        if (origin.capture_id !== (entry.request.origin as Extract<SyntheticOrigin, { kind: "CAPTURED_WINDOW" }>).capture_id) {
          throw new Error("Captured source identity changed");
        }
        entry.preparation = null; this.connect(entry, true);
      }).catch(error => {
        if (!controller.signal.aborted && !entry.closed) { entry.preparation = null; this.recover(entry, String(error)); }
      });
      return;
    }
    let socket: SyntheticSocket;
    try { socket = this.socketFactory(); }
    catch (error) { this.recover(entry, String(error)); return; }
    entry.socket = socket;
    const current = () => !entry.closed && entry.socket === socket;
    let first = true;
    let assembly: { state: SyntheticSnapshot; rows: SyntheticRow[]; total: number } | null = null;
    socket.onopen = () => { if (current()) socket.send(JSON.stringify(entry.request)); };
    socket.onmessage = event => {
      if (!current() || event.data === "pong") return;
      try {
        const message: unknown = JSON.parse(event.data);
        const previous = first ? EMPTY_SYNTHETIC : entry.state;
        const envelope = message as Record<string, unknown> | null;
        let state: SyntheticSnapshot;
        if (envelope?.["type"] === "snapshot_chunk") {
          const from = envelope["from_index"], total = envelope["total"], rows = envelope["rows"];
          if (typeof from !== "number" || !Number.isSafeInteger(from) || from < 0
            || typeof total !== "number" || !Number.isSafeInteger(total) || total < 0 || total > 50_000
            || !Array.isArray(rows) || rows.length > entry.request.limit || from + rows.length > total
            || typeof envelope["complete"] !== "boolean" || (!rows.length && total !== 0)) throw new Error("Invalid synthetic snapshot chunk");
          const part = adoptSynthetic(EMPTY_SYNTHETIC, { ...envelope, type: "snapshot", total: from + rows.length }, entry.request);
          if (!assembly) {
            if (from !== 0) throw new Error("Synthetic snapshot prefix missing");
            assembly = { state: part, rows: [], total };
          }
          if (from !== assembly.rows.length || total !== assembly.total || part.generation !== assembly.state.generation
            || part.revision !== assembly.state.revision || part.seriesId !== assembly.state.seriesId) throw new Error("Synthetic snapshot changed between chunks");
          assembly.rows.push(...part.rows);
          entry.pendingRows = assembly.rows.length;
          this.checkRows();
          if (envelope["complete"] !== (entry.pendingRows === total)) throw new Error("Invalid synthetic snapshot completion");
          if (!envelope["complete"]) return;
          state = Object.freeze({ ...part, from: 0, total, rows: Object.freeze(assembly.rows) });
          assembly = null; entry.pendingRows = 0;
        } else {
          if (assembly) throw new Error("Synthetic snapshot interrupted");
          state = adoptSynthetic(previous, message, entry.request);
          if (first && envelope?.["type"] !== "snapshot") throw new Error("Synthetic snapshot required");
          if (entry.request.complete_window && envelope?.["type"] === "snapshot" && state.from !== 0) throw new Error("Synthetic snapshot prefix missing");
        }
        this.checkRows(entry, state.rows.length);
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
  private checkRows(replace?: Entry, rows = 0) {
    const total = [...this.entries.values()].reduce((sum, entry) =>
      sum + (entry === replace ? rows : entry.state.rows.length) + entry.pendingRows + (entry.capture?.rows.length ?? 0), 0);
    if (total > 100_000) throw new Error("Shared synthetic cache budget exceeded");
  }
  private recover(entry: Entry, reason: string) {
    const socket = entry.socket;
    entry.socket = null;
    entry.pendingRows = 0;
    socket?.close();
    if (entry.closed || entry.timer) return;
    this.publish(entry, Object.freeze({ ...entry.state, status: "stale", reason }));
    entry.timer = setTimeout(() => {
      entry.timer = null;
      this.connect(entry);
    }, Math.min(10_000, 500 * 2 ** Math.min(entry.attempts++, 5)));
  }
  diagnostics() {
    return { sharedSeries: this.entries.size, retainedRows: [...this.entries.values()].reduce((sum, entry) => sum + entry.state.rows.length, 0),
      capturedInputRows: [...this.entries.values()].reduce((sum, entry) => sum + (entry.capture?.rows.length ?? 0), 0) };
  }
  closeAll() {
    this.generation++;
    for (const entry of this.entries.values()) {
      entry.closed = true;
      if (entry.timer) clearTimeout(entry.timer);
      entry.preparation?.abort();
      entry.socket?.close();
    }
    this.entries.clear();
  }
}
