import { API_BASE, httpBaseToWsBase } from "../../../services/apiConfig.js";
import { adoptSynthetic, EMPTY_SYNTHETIC, firstSyntheticSourceTime, prependSyntheticPage, type SyntheticRequest,
  type SyntheticSnapshot, type SyntheticOrigin } from "./syntheticSeries.js";
import type { KlineBar } from "../marketDataTypes.js";

/** Rows the browser keeps across every shared synthetic series. */
export const SYNTHETIC_CACHE_ROWS = 100_000;
const PAGE_RETRIES = 3;

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
  /** What consumers see: a contiguous output range [from, total) that always ends at the live tail. */
  state: SyntheticSnapshot;
  /** A newer snapshot still paging back to `target`; published once it covers it. */
  draft: SyntheticSnapshot | null;
  socket: SyntheticSocket | null;
  timer: ReturnType<typeof setTimeout> | null;
  listeners: Set<() => void>;
  attempts: number;
  closed: boolean;
  capture?: CaptureBody;
  preparation: AbortController | null;
  /** Earliest source time (seconds) a consumer needs; older pages load until outputs reach it. */
  target: number | null;
  paging: AbortController | null;
  pageRetries: number;
  awaitingRevision: boolean;
  pageLimit: string | null;
}
export interface SyntheticView {
  getRequest(): SyntheticRequest;
  getSnapshot(): SyntheticSnapshot;
  subscribe(listener: () => void): () => void;
  release(): void;
  /** Loads the page of outputs before the first retained one. */
  loadOlder(): void;
  /** Keeps loading older pages until the outputs reach this source time (seconds). */
  cover(sourceTime: number): void;
}
export interface SyntheticAcquireOptions {
  capture?: CaptureBody;
  /** Source time (seconds) the first published snapshot must already cover. */
  cover?: number | null;
}

/** Shared immutable backend replica. Charts own separate display windows.
 *
 * The stream sends the newest page of a definition and its live patches.
 * Older outputs of the same definition page in by ordinal cursor
 * (POST /synthetic/query `before`) when a chart scrolls to them or needs a
 * source time, so a large output no longer transfers before the first paint.
 * Every consumer of a definition sees the same contiguous range, which always
 * ends at the live tail; a page never moves another chart's live boundary. */
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

  async acquireCaptured(request: SyntheticRequest, rows: readonly KlineBar[], scope: string, cutoff_ms: number,
    signal: AbortSignal, cover: number | null = null) {
    const generation = this.generation;
    const body: CaptureBody = { source: request.source, scope, cutoff_ms, rows: rows.map(row => ({
      time: row.time, open: Number(row.open), high: Number(row.high), low: Number(row.low), close: Number(row.close),
      ...(row.volume == null ? {} : { volume: Number(row.volume) }), is_closed: row.is_closed !== false,
    })) };
    const origin = await this.registerCapture(body, signal);
    signal.throwIfAborted();
    if (generation !== this.generation) throw new DOMException("Synthetic owner changed", "AbortError");
    return this.acquire({ ...request, origin }, { capture: body, cover });
  }

  acquire(request: SyntheticRequest, options: SyntheticAcquireOptions = {}): SyntheticView {
    const { capture, cover = null } = options;
    const key = JSON.stringify(request);
    let entry = this.entries.get(key);
    if (!entry) {
      if (this.entries.size >= 32) throw new Error("Synthetic subscription budget exceeded");
      entry = { request, state: EMPTY_SYNTHETIC, draft: null, socket: null, timer: null, listeners: new Set(), attempts: 0,
        closed: false, preparation: null, target: cover, paging: null, pageRetries: 0, awaitingRevision: false,
        pageLimit: null, ...(capture ? { capture } : {}) };
      this.entries.set(key, entry);
      try { this.checkRows(); } catch (error) { this.entries.delete(key); throw error; }
    } else if (cover !== null) {
      this.cover(entry, cover);
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
          target.paging?.abort();
          target.socket?.close();
          this.entries.delete(key);
        }
      },
      loadOlder: () => { if (!released) this.page(target); },
      cover: sourceTime => { if (!released) this.cover(target, sourceTime); },
    };
  }

  private publish(entry: Entry, state: SyntheticSnapshot) {
    entry.state = (state.pageLimit ?? null) === entry.pageLimit ? state
      : Object.freeze({ ...state, pageLimit: entry.pageLimit });
    for (const listener of [...entry.listeners]) listener();
  }
  private covers(entry: Entry, state: SyntheticSnapshot) {
    if (entry.target === null || state.from === 0 || state.status !== "ready" || !state.rows.length) return true;
    // Strict: bricks sharing the target's source time may sit on the previous page.
    const first = firstSyntheticSourceTime(state);
    return first === null || first < entry.target;
  }
  private cover(entry: Entry, sourceTime: number) {
    if (!Number.isFinite(sourceTime)) return;
    entry.target = entry.target === null ? sourceTime : Math.min(entry.target, sourceTime);
    if (!this.covers(entry, entry.draft ?? entry.state)) this.page(entry);
  }
  /** Publishes a waiting snapshot with what it has, e.g. when paging stops. */
  private settle(entry: Entry) {
    const state = entry.draft ?? entry.state;
    entry.draft = null;
    this.publish(entry, state);
  }
  private stopPaging(entry: Entry, reason: string) {
    entry.pageLimit = reason;
    this.settle(entry);
  }
  private page(entry: Entry) {
    if (entry.closed || entry.paging || entry.pageLimit) return;
    const working = entry.draft ?? entry.state;
    if (working.status !== "ready" || working.from === 0 || !working.seriesId) return;
    const controller = new AbortController();
    entry.paging = controller;
    const owns = () => !controller.signal.aborted && !entry.closed && entry.paging === controller;
    void this.fetcher(`${API_BASE}/synthetic/query`, {
      method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal,
      body: JSON.stringify({ ...entry.request, before: working.from, generation: working.generation }),
    }).then(async response => {
      const body: unknown = await response.json().catch(() => null);
      if (!owns()) return;
      entry.paging = null;
      if (!response.ok) {
        const detail = body && typeof body === "object" ? String((body as { detail?: unknown }).detail ?? "") : "";
        // A new generation reaches this replica through its stream, which
        // restarts paging from the new newest page.
        if (response.status === 409 && /generation changed/.test(detail)) return;
        this.stopPaging(entry, detail || `Synthetic page unavailable (${response.status})`);
        return;
      }
      const current = entry.draft ?? entry.state;
      const result = prependSyntheticPage(current, body, entry.request);
      if (result.kind === "stale") return;
      if (result.kind === "revision") {
        // The backend is ahead of this stream: page again after the patch lands.
        if (result.ahead) { entry.awaitingRevision = true; return; }
        if (++entry.pageRetries > PAGE_RETRIES) this.stopPaging(entry, "Synthetic pages kept changing");
        else this.page(entry);
        return;
      }
      try {
        this.checkRows(entry, result.state.rows.length + (entry.draft ? entry.state.rows.length : 0));
      } catch (error) {
        this.stopPaging(entry, error instanceof Error ? error.message : String(error));
        return;
      }
      entry.pageRetries = 0;
      if (entry.draft) {
        entry.draft = result.state;
        if (this.covers(entry, result.state)) this.settle(entry);
        else this.page(entry);
      } else {
        this.publish(entry, result.state);
        if (!this.covers(entry, result.state)) this.page(entry);
      }
    }).catch(error => {
      if (!owns()) return;
      entry.paging = null;
      this.stopPaging(entry, error instanceof Error ? error.message : String(error));
    });
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
    socket.onopen = () => { if (current()) socket.send(JSON.stringify(entry.request)); };
    socket.onmessage = event => {
      if (!current() || event.data === "pong") return;
      try {
        const message: unknown = JSON.parse(event.data);
        const type = (message as Record<string, unknown> | null)?.["type"];
        const state = adoptSynthetic(first ? EMPTY_SYNTHETIC : entry.draft ?? entry.state, message, entry.request);
        if (first && type !== "snapshot") throw new Error("Synthetic snapshot required");
        first = false;
        entry.attempts = 0;
        if (type === "snapshot") {
          // A snapshot (first, resync or reconnect) restarts at the newest
          // page. Keep the range consumers already loaded: page back to it
          // before publishing, so a resync never empties a browsed view.
          entry.paging?.abort(); entry.paging = null;
          entry.pageRetries = 0; entry.awaitingRevision = false; entry.pageLimit = null;
          const shown = firstSyntheticSourceTime(entry.state);
          if (shown !== null && entry.state.status === "ready") entry.target = Math.min(entry.target ?? shown, shown);
          if (this.covers(entry, state)) {
            this.checkRows(entry, state.rows.length);
            entry.draft = null;
            this.publish(entry, state);
          } else {
            this.checkRows(entry, state.rows.length + entry.state.rows.length);
            entry.draft = state;
            this.page(entry);
          }
        } else if (entry.draft) {
          this.checkRows(entry, state.rows.length + entry.state.rows.length);
          entry.draft = state;
        } else {
          this.checkRows(entry, state.rows.length);
          this.publish(entry, state);
        }
        if (state.status !== "ready") this.recover(entry, state.reason ?? "Synthetic series unavailable");
        else if (entry.awaitingRevision) { entry.awaitingRevision = false; this.page(entry); }
      } catch (error) {
        this.recover(entry, error instanceof Error ? error.message : String(error));
      }
    };
    socket.onclose = () => { if (current()) this.recover(entry, "Synthetic connection interrupted"); };
    socket.onerror = () => { if (current()) this.recover(entry, "Synthetic connection interrupted"); };
  }
  private retainedRows(entry: Entry) {
    return entry.state.rows.length + (entry.draft?.rows.length ?? 0) + (entry.capture?.rows.length ?? 0);
  }
  /** `rows` replaces the outputs `replace` would retain after a change. */
  private checkRows(replace?: Entry, rows = 0) {
    const total = [...this.entries.values()].reduce((sum, entry) =>
      sum + (entry === replace ? rows + (entry.capture?.rows.length ?? 0) : this.retainedRows(entry)), 0);
    if (total > SYNTHETIC_CACHE_ROWS) throw new Error("Shared synthetic cache budget exceeded");
  }
  private recover(entry: Entry, reason: string) {
    const socket = entry.socket;
    entry.socket = null;
    entry.paging?.abort(); entry.paging = null;
    entry.draft = null; entry.awaitingRevision = false;
    socket?.close();
    if (entry.closed || entry.timer) return;
    this.publish(entry, Object.freeze({ ...entry.state, status: "stale", reason }));
    entry.timer = setTimeout(() => {
      entry.timer = null;
      this.connect(entry);
    }, Math.min(10_000, 500 * 2 ** Math.min(entry.attempts++, 5)));
  }
  diagnostics() {
    const entries = [...this.entries.values()];
    return { sharedSeries: entries.length,
      retainedRows: entries.reduce((sum, entry) => sum + entry.state.rows.length + (entry.draft?.rows.length ?? 0), 0),
      pagedSeries: entries.filter(entry => entry.state.from > 0).length,
      capturedInputRows: entries.reduce((sum, entry) => sum + (entry.capture?.rows.length ?? 0), 0) };
  }
  closeAll() {
    this.generation++;
    for (const entry of this.entries.values()) {
      entry.closed = true;
      if (entry.timer) clearTimeout(entry.timer);
      entry.preparation?.abort();
      entry.paging?.abort();
      entry.socket?.close();
    }
    this.entries.clear();
  }
}
