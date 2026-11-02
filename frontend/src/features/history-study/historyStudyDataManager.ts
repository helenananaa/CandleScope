import { request } from "../../services/api.js";
import { API_BASE } from "../../services/apiConfig.js";
import type { HistoryStudyView, HistoryStudyCursor, StudyNote, SavedStudySummary } from "./historyStudyTypes.js";
import type { MarketSeries } from "../market-data/marketDataTypes.js";
import type { StudyJournalData } from "./historyStudyJournal.js";

type Method = "GET" | "POST" | "PATCH";
type Transport = (path: string, options: { method?: Method; body?: unknown; signal: AbortSignal }) => Promise<unknown>;
type JournalTransport = (accountId: string, series: MarketSeries, cursorMs: number, signal: AbortSignal) => Promise<unknown>;
const pathId = encodeURIComponent;

/** Owns each observer's cancellation, not a chart selection or public cache.
 * Study inputs and notes remain in their durable service; no order API exists. */
export class HistoryStudyDataManager {
  private requests = new Set<AbortController>();
  private closed = false;
  constructor(private transport: Transport = (path, options) => request(`${API_BASE}/history-studies${path}`, options),
    private journalTransport: JournalTransport = (accountId, series, cursorMs, signal) => {
      const query = new URLSearchParams({ exchange: series.exchange, marketType: series.marketType,
        symbol: series.symbol, cursorMs: String(cursorMs), limit: "100" });
      return request(`${API_BASE}/trading/accounts/${pathId(accountId)}/journal-at-time?${query}`, { signal });
    }) {}
  private async observe<T>(read: (signal: AbortSignal) => Promise<unknown>, signal?: AbortSignal): Promise<T> {
    if (this.closed) throw new Error("History study manager is closed");
    signal?.throwIfAborted();
    const controller = new AbortController();
    const abort = () => controller.abort(signal?.reason);
    signal?.addEventListener("abort", abort, { once: true });
    this.requests.add(controller);
    try {
      const result = await read(controller.signal);
      controller.signal.throwIfAborted();
      return result as T;
    } finally {
      signal?.removeEventListener("abort", abort);
      this.requests.delete(controller);
    }
  }
  call<T>(path: string, method: Method, body?: unknown, signal?: AbortSignal): Promise<T> {
    return this.observe(inner => this.transport(path, { method, ...(body === undefined ? {} : { body }), signal: inner }), signal);
  }
  async journalAtTime(accountId: string, series: MarketSeries, cursorMs: number, signal?: AbortSignal): Promise<StudyJournalData> {
    const result = await this.observe<StudyJournalData>(inner => this.journalTransport(accountId, series, cursorMs, inner), signal);
    if (result.accountId !== accountId || result.cursorMs !== cursorMs
      || [...result.original, ...result.reviews].some(note => note.accountId !== accountId)) throw new Error("Journal projection does not match its read owner");
    return result;
  }
  read(owner: string, signal?: AbortSignal) { return this.call<HistoryStudyView>(`/views/${pathId(owner)}`, "GET", undefined, signal); }
  capture(owner: string, input: unknown, signal?: AbortSignal) { return this.call<HistoryStudyView>(`/views/${pathId(owner)}`, "POST", input, signal); }
  move(owner: string, body: unknown, signal?: AbortSignal) { return this.call<HistoryStudyCursor>(`/views/${pathId(owner)}`, "PATCH", body, signal); }
  saved(owner: string, signal?: AbortSignal) { return this.call<{ studies: SavedStudySummary[] }>(`/saved/${pathId(owner)}`, "GET", undefined, signal); }
  select(owner: string, action: "activate" | "remove", body: unknown, signal?: AbortSignal) {
    return this.call<HistoryStudyView>(`/saved/${pathId(owner)}/${action}`, "POST", body, signal);
  }
  notes(studyId: string, cursorMs: number, signal?: AbortSignal) {
    return this.call<{ notes: StudyNote[] }>(`/${pathId(studyId)}/notes?cursorMs=${cursorMs}`, "GET", undefined, signal);
  }
  saveNote(studyId: string, body: unknown) { return this.call<StudyNote>(`/${pathId(studyId)}/notes`, "POST", body); }
  diagnostics() { return { requests: this.requests.size, closed: this.closed }; }
  dispose() {
    this.closed = true;
    for (const controller of this.requests) controller.abort();
    this.requests.clear();
  }
}
