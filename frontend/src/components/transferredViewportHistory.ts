import { toEpochSeconds, type EpochSeconds } from "../features/market-data/marketDataTypes.js";

/** One bounded, contiguous history fill belonging to an explicit viewport transfer.
 * Ordinary left-edge gestures still request only one page per interaction. */
export class TransferredViewportHistory {
  private inFlight = false;
  private previousBoundary: number | null = null;
  private requests = 0;
  private stopped = false;

  constructor(readonly datasetKey: string, readonly targetFrom: number, readonly maxPages = 20) {}

  claim(input: {
    datasetKey: string | null;
    firstTime: number | undefined;
    loading: boolean;
    canLoad: boolean;
    hasHandler: boolean;
  }): number | null {
    if (this.stopped || this.inFlight || input.loading || input.firstTime === undefined) return null;
    if (input.datasetKey !== this.datasetKey) return null;
    const first = input.firstTime;
    if (!Number.isFinite(first) || !Number.isFinite(this.targetFrom)
      || first <= this.targetFrom || !input.canLoad || !input.hasHandler
      || this.requests >= this.maxPages
      || (this.previousBoundary !== null && first >= this.previousBoundary)) {
      this.stopped = true;
      return null;
    }
    this.previousBoundary = first;
    this.requests += 1;
    this.inFlight = true;
    return first;
  }

  settle(succeeded: boolean): void {
    this.inFlight = false;
    if (!succeeded) this.stopped = true;
  }

  async loadPage(input: Parameters<TransferredViewportHistory["claim"]>[0],
    load: (before: EpochSeconds) => Promise<void>): Promise<boolean> {
    const claimed = this.claim(input);
    // The time converter intentionally accepts numeric-like values, including
    // null -> 0. A stop/wait signal must never reach that conversion or loader.
    if (claimed === null) return false;
    const before = toEpochSeconds(claimed);
    if (before === null) { this.settle(false); return false; }
    try {
      await load(before);
      this.settle(true);
    } catch {
      this.settle(false);
    }
    return true;
  }
}
