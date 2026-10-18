import { estimateOutputWarmupBars } from "../indicators/indicatorRangePlanning.js";
import type { IndicatorDefinition } from "../indicators/indicatorTypes.js";

// Bound automatic work. Longer studies remain available through ordinary
// history paging; a parameter typo must not download an unbounded archive.
export const MAX_AUTOMATIC_REPLAY_WARMUP_BARS = 2_000;

export function replayHistoryWarmupTarget(indicators: readonly IndicatorDefinition[]): number {
  let target = 0;
  for (const indicator of indicators) {
    if (indicator.visible === false) continue;
    const estimate = estimateOutputWarmupBars(indicator);
    if (Number.isFinite(estimate)) target = Math.max(target, Math.floor(estimate) + 1);
  }
  return Math.min(MAX_AUTOMATIC_REPLAY_WARMUP_BARS, Math.max(0, target));
}

export function replayHistoryNeedsWarmup(input: {
  barCount: number;
  targetBars: number;
  hasMore: boolean;
  loading: boolean;
  error: string | null;
  rightTruncated: boolean;
}): boolean {
  return input.targetBars > input.barCount && input.hasMore && !input.loading
    && input.error === null && !input.rightTruncated;
}
