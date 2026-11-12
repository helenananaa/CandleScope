import type { DisplayRow } from "../../chart-representation/chartRepresentationTypes.js";
import type { MarketSeries } from "../marketDataTypes.js";
import type { SeriesWindowView } from "../window/seriesWindowView.js";
import { buildSeriesWindowKey } from "../window/seriesWindowKey.js";
import { EMPTY_SYNTHETIC, syntheticRequest, type SyntheticSnapshot } from "./syntheticSeries.js";
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

  constructor(private manager: SyntheticSeriesManager, private source: MarketSeries,
    private reader: SeriesWindowView, private transform: "renko" | "heikin-ashi",
    private settings: { mode?: string; boxSize?: number; atrLength?: number }) {}

  start() {
    this.refreshRange();
    this.releaseSource = this.reader.subscribe(() => this.refreshRange());
  }
  private refreshRange() {
    if (this.reader.seriesKey !== buildSeriesWindowKey(this.source)) {
      this.detach();
      this.rangeKey = "";
      this.error = "preparing";
      this.notify();
      return;
    }
    const first = this.reader.first(), last = this.reader.last();
    const key = first && last ? `${first.time}:${last.time}` : "";
    if (key === this.rangeKey) return;
    this.detach();
    this.rangeKey = key;
    this.error = null;
    if (first && last) {
      try {
        this.view = this.manager.acquire(syntheticRequest(this.source, this.transform, this.settings, first.time, last.time));
        this.releaseView = this.view.subscribe(() => this.notify());
      } catch (error) {
        this.error = error instanceof Error ? error.message : String(error);
      }
    }
    this.notify();
  }
  private detach() {
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
  rows(): DisplayRow[] { return Array.from(this.snapshot().rows); }
  get configurationKey() {
    const snapshot = this.snapshot();
    return `backend:${this.bindingId}:${JSON.stringify([this.source, this.transform, this.settings])}:${this.rangeKey}:${snapshot.generation}`;
  }
  status = () => this.error ?? this.snapshot().status;
}
