/**
 * A chart strategy run covers the chart's stored series (RC 34). Right after a market switch the chart
 * has not committed that series yet, and the backend has no range to prepare: a run waits for it here.
 */

export interface ChartStrategyChartDataState {
  barCount: number;
  loading: boolean;
  initialHistoryPending: boolean;
  /** The committed window's series; during a switch it still names the previous one. */
  meta: { symbol?: string; interval?: string; optimistic?: boolean };
}

/** The chart has committed the first window of this session's series. */
export function chartStrategyChartDataReady(
  data: ChartStrategyChartDataState,
  session: { symbol: string; interval: string },
): boolean {
  return data.barCount > 0 && !data.loading && !data.initialHistoryPending && data.meta.optimistic !== true
    && data.meta.symbol === session.symbol && data.meta.interval === session.interval;
}

/** Holds runs until the chart's data is ready; an aborted run stops waiting. */
export class ChartStrategyChartDataGate {
  private readonly waiters = new Set<() => void>();

  constructor(private current = true) {}

  get ready(): boolean {
    return this.current;
  }

  set(ready: boolean): void {
    this.current = ready;
    if (!ready) return;
    const waiters = [...this.waiters];
    this.waiters.clear();
    waiters.forEach((release) => release());
  }

  wait(signal?: AbortSignal): Promise<void> {
    if (this.current) return Promise.resolve();
    if (signal?.aborted) return Promise.reject(abortReason(signal));
    return new Promise<void>((resolve, reject) => {
      const release = () => {
        signal?.removeEventListener("abort", abort);
        resolve();
      };
      const abort = () => {
        this.waiters.delete(release);
        reject(abortReason(signal));
      };
      this.waiters.add(release);
      signal?.addEventListener("abort", abort, { once: true });
    });
  }
}

function abortReason(signal: AbortSignal | undefined): Error {
  const reason: unknown = signal?.reason;
  return reason instanceof Error ? reason : new DOMException("Waiting for chart data stopped", "AbortError");
}
