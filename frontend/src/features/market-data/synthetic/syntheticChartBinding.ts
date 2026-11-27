import type { DisplayRow } from "../../chart-representation/chartRepresentationTypes.js";
import type { SeriesWindowView } from "../window/seriesWindowView.js";
import { buildSeriesWindowKey } from "../window/seriesWindowKey.js";
import { EMPTY_SYNTHETIC, firstSyntheticSourceTime, syntheticRequest, type SyntheticSnapshot, type SyntheticSettings, type SyntheticTransform, type BackendSyntheticSource } from "./syntheticSeries.js";
import type { SyntheticSeriesManager, SyntheticView } from "./syntheticSeriesManager.js";

let nextBindingId = 1;

/** One chart's range/lease. The workspace replica is immutable and shared. */
export class SyntheticChartBinding {
  private readonly bindingId = nextBindingId++;
  private view: SyntheticView | null = null;
  private releaseView: (() => void) | null = null;
  private releaseSource: (() => boolean) | null = null;
  private listeners = new Set<() => void>();
  private rangeKey = "";
  private error: string | null = null;
  private captureAbort: AbortController | null = null;
  private epoch = 0;
  /** First source time (seconds) this chart last showed; a new definition covers it before it paints. */
  private visibleSourceTime: number | null = null;

  constructor(private manager: SyntheticSeriesManager, private source: BackendSyntheticSource,
    private reader: SeriesWindowView, private transform: SyntheticTransform,
    private settings: SyntheticSettings) {}

  start() {
    this.refreshRange();
    this.releaseSource = this.reader.subscribe(() => this.refreshRange());
  }
  private refreshRange() {
    if (this.reader.seriesKey !== (this.source.syntheticSeriesKey ?? buildSeriesWindowKey(this.source))) {
      this.detach();
      this.rangeKey = "";
      this.error = "preparing";
      this.notify();
      return;
    }
    const first = this.reader.first(), last = this.reader.last();
    const key = first && last ? `${first.time}:${last.time}${this.source.syntheticCapture ? `:${this.reader.version}` : ""}` : "";
    if (key === this.rangeKey) return;
    this.detach();
    this.rangeKey = key;
    this.error = null;
    if (first && last) {
      try {
        const request = syntheticRequest(this.source, this.transform, this.settings, first.time, last.time);
        const capture = this.source.syntheticCapture;
        // A source window that grew to the left still shows the same place:
        // page the new definition back to it instead of painting its tail.
        const seen = this.visibleSourceTime;
        const cover = seen !== null && seen >= first.time && seen <= last.time ? seen : null;
        if (capture) {
          const controller = new AbortController(), epoch = this.epoch; this.captureAbort = controller;
          void this.manager.acquireCaptured(request, this.reader.snapshot(), capture.scope, capture.cutoff_ms, controller.signal, cover).then(view => {
            if (controller.signal.aborted || epoch !== this.epoch) { view.release(); return; }
            this.view = view; this.releaseView = view.subscribe(() => this.notify()); this.notify();
          }).catch(error => {
            if (!controller.signal.aborted && epoch === this.epoch) { this.error = String(error); this.notify(); }
          });
        } else {
          this.view = this.manager.acquire(request, { cover });
          this.releaseView = this.view.subscribe(() => this.notify());
        }
      } catch (error) {
        this.error = error instanceof Error ? error.message : String(error);
      }
    }
    this.notify();
  }
  private detach() {
    this.epoch++; this.captureAbort?.abort(); this.captureAbort = null;
    this.releaseView?.(); this.releaseView = null;
    this.view?.release(); this.view = null;
  }
  close() {
    this.releaseSource?.(); this.releaseSource = null;
    this.detach();
    this.rangeKey = "";
  }
  private notify() { for (const listener of [...this.listeners]) listener(); }
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  snapshot(): SyntheticSnapshot { return this.view?.getSnapshot() ?? EMPTY_SYNTHETIC; }
  request() { return this.view?.getRequest() ?? null; }
  rows(): DisplayRow[] { return Array.from(this.snapshot().rows); }
  get configurationKey() {
    const snapshot = this.snapshot();
    return `backend:${this.bindingId}:${JSON.stringify([this.source, this.transform, this.settings])}:${this.rangeKey}:${snapshot.generation}`;
  }
  status = () => this.error ?? this.snapshot().status;
  /** Why older outputs stopped loading, or null. */
  pageLimit = () => this.snapshot().pageLimit ?? null;
  /** True while outputs of this definition exist before the first retained one. */
  hasOlderOutputs() {
    const snapshot = this.snapshot();
    return snapshot.status === "ready" && snapshot.from > 0 && !snapshot.pageLimit;
  }
  /** False while `sourceTime` (seconds) lies before the retained outputs and older ones can still load. */
  coversSourceTime(sourceTime: number) {
    if (!this.hasOlderOutputs()) return true;
    const first = firstSyntheticSourceTime(this.snapshot());
    return first === null || first <= sourceTime;
  }
  /** Loads the previous page of outputs; the chart calls this at its left edge. */
  loadOlder() { this.view?.loadOlder(); }
  /** Loads older outputs until they reach `sourceTime` (seconds), e.g. for Go to date. */
  cover(sourceTime: number) { this.view?.cover(sourceTime); }
  /** The chart reports the first source time (seconds) it shows. */
  noteVisibleSourceTime(sourceTime: number | null | undefined) {
    if (typeof sourceTime === "number" && Number.isFinite(sourceTime)) this.visibleSourceTime = sourceTime;
  }
}
