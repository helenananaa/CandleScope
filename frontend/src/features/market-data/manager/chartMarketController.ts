import type { MarketDataService } from "../marketDataService.js";
import type { MarketSeries } from "../marketDataTypes.js";
import type { MarketWarmLease } from "./marketWarmQueue.js";
import { buildSeriesWindowKey } from "../window/seriesWindowKey.js";

export interface ChartMarketControllerOptions {
  data: Pick<MarketDataService, "warm" | "prepareForeground">;
  owner: string;
  hoverDwellMs?: number;
  handoffTtlMs?: number;
  schedule?: (work: () => void, delayMs: number) => unknown;
  cancel?: (timer: unknown) => void;
}

/** Per-chart selection intent coordinator. Session capability/persistence stays
 * in chart-session; shared transport/cache stay in DataManager. This boundary
 * hands off hover demand before foreground effects can cancel it. */
export class ChartMarketController {
  private generation = 0;
  private previewKey: string | null = null;
  private previewTimer: unknown = null;
  private previewLease: MarketWarmLease | null = null;
  private handoffTimer: unknown = null;
  private handoff: { release(): void } | null = null;
  private readonly schedule: NonNullable<ChartMarketControllerOptions["schedule"]>;
  private readonly cancel: NonNullable<ChartMarketControllerOptions["cancel"]>;

  constructor(private readonly options: ChartMarketControllerOptions) {
    this.schedule = options.schedule ?? ((work, delay) => setTimeout(work, delay));
    this.cancel = options.cancel ?? (timer => clearTimeout(timer as ReturnType<typeof setTimeout>));
  }

  preview(series: MarketSeries, nativeIntervals: readonly string[]): void {
    const key = String(buildSeriesWindowKey(series));
    if (key === this.previewKey) return;
    this.cancelPreview();
    this.previewKey = key;
    const generation = this.generation;
    const input = { ...series }, native = [...nativeIntervals];
    this.previewTimer = this.schedule(() => {
      this.previewTimer = null;
      if (generation !== this.generation || this.previewKey !== key) return;
      this.previewLease = this.options.data.warm(input, {
        owner: `${this.options.owner}:hover`, reason: "hover", nativeIntervals: native,
      });
    }, this.options.hoverDwellMs ?? 150);
  }

  cancelPreview(): void {
    this.previewKey = null;
    if (this.previewTimer !== null) this.cancel(this.previewTimer);
    this.previewTimer = null;
    this.previewLease?.release(); this.previewLease = null;
  }

  activate(series: MarketSeries): { generation: number; isCurrent(): boolean } {
    // Promotion must precede pointer-leave cancellation and foreground work.
    const next = this.options.data.prepareForeground(series);
    this.cancelPreview();
    this.releaseHandoff();
    this.handoff = next;
    const generation = ++this.generation;
    this.handoffTimer = this.schedule(() => {
      if (this.generation === generation) this.releaseHandoff();
    }, this.options.handoffTtlMs ?? 5_000);
    return Object.freeze({ generation, isCurrent: () => this.generation === generation });
  }

  /** Reusable after React StrictMode cleanup; old intent tokens stay invalid. */
  releaseAll(): void {
    this.generation += 1;
    this.cancelPreview(); this.releaseHandoff();
  }

  private releaseHandoff(): void {
    if (this.handoffTimer !== null) this.cancel(this.handoffTimer);
    this.handoffTimer = null;
    this.handoff?.release(); this.handoff = null;
  }
}
