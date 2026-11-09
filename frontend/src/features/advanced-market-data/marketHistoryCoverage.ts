import type { MarketHistoryPayload } from "./advancedMarketDataTypes.js";

export interface MarketHistoryRange {
  startMs: number;
  endMs: number;
}

export type MarketHistoryPageDirection = "forward" | "backward";

/** Stop retrying an unresolved native page until explicit retry or context change. */
export class HistoryGapRetryBudget {
  private readonly failures = new Map<string, number>();
  blocked(key: string): boolean { return (this.failures.get(key) || 0) >= 3; }
  fail(key: string): boolean {
    this.failures.set(key, (this.failures.get(key) || 0) + 1);
    if (this.failures.size > 64) this.failures.delete(this.failures.keys().next().value!);
    return !this.blocked(key);
  }
  clear(): void { this.failures.clear(); }
}

// Binance USD-M retains 30 days and the smallest native OI period is 5m.
const MAX_OI_RETRY_CELLS = 30 * 24 * 12;

export function openInterestSampleCells(
  range: MarketHistoryRange,
  stepMs: number,
): MarketHistoryRange | null {
  const startMs = Math.ceil(range.startMs / stepMs) * stepMs;
  const endMs = (Math.floor(range.endMs / stepMs) + 1) * stepMs - 1;
  return startMs <= range.endMs ? { startMs, endMs } : null;
}

/** Holds only acquisition attempts. These ranges never become local coverage. */
export class OpenInterestHistoryRetryBudget {
  private readonly attempts = new Map<number, { failures: number; retryAt: number }>();

  deferred(
    requested: MarketHistoryRange,
    stepMs: number,
    nowMs: number,
  ): { ranges: MarketHistoryRange[]; retryAt: number | null } {
    const ranges: MarketHistoryRange[] = [];
    let retryAt: number | null = null;
    for (const [startMs, attempt] of this.attempts) {
      const endMs = startMs + stepMs - 1;
      if (endMs < requested.startMs || startMs > requested.endMs) continue;
      if (attempt.failures >= 3 || attempt.retryAt > nowMs) {
        ranges.push({ startMs, endMs });
      }
      if (attempt.failures < 3 && attempt.retryAt > nowMs) {
        retryAt = Math.min(retryAt ?? attempt.retryAt, attempt.retryAt);
      }
    }
    return { ranges, retryAt };
  }

  accept(ranges: readonly { start_ms: number; end_ms: number }[]): void {
    for (const sample of this.attempts.keys()) {
      if (ranges.some((range) => range.start_ms <= sample && sample <= range.end_ms)) {
        this.attempts.delete(sample);
      }
    }
  }

  fail(
    range: MarketHistoryRange,
    stepMs: number,
    nowMs: number,
    retryDelayMs: number,
  ): boolean {
    const cells = openInterestSampleCells(range, stepMs);
    if (!cells) return false;
    let retryAllowed = false;
    const first = Math.max(cells.startMs, cells.endMs + 1 - MAX_OI_RETRY_CELLS * stepMs);
    for (let sample = first; sample <= cells.endMs; sample += stepMs) {
      const previous = this.attempts.get(sample);
      const failures = Math.min(3, (previous?.failures || 0) + 1);
      this.attempts.set(sample, { failures, retryAt: nowMs + retryDelayMs });
      retryAllowed ||= failures < 3;
    }
    while (this.attempts.size > MAX_OI_RETRY_CELLS) {
      this.attempts.delete(this.attempts.keys().next().value!);
    }
    return retryAllowed;
  }

  clear(): void { this.attempts.clear(); }
}

function normalizedRange(range: MarketHistoryRange): MarketHistoryRange {
  const startMs = Math.max(0, Math.floor(Math.min(range.startMs, range.endMs)));
  const endMs = Math.max(startMs, Math.ceil(Math.max(range.startMs, range.endMs)));
  return { startMs, endMs };
}

export function clampHistoryRangeToNow(
  requested: MarketHistoryRange,
  nowMs: number = Date.now(),
): MarketHistoryRange | null {
  const target = normalizedRange(requested);
  const upperBound = Math.max(0, Math.floor(nowMs));
  if (target.startMs > upperBound) return null;
  return {
    startMs: target.startMs,
    endMs: Math.min(target.endMs, upperBound),
  };
}

export function mergeHistoryCoverage(
  current: readonly MarketHistoryRange[],
  incoming: MarketHistoryRange,
): MarketHistoryRange[] {
  const ranges = [...current.map(normalizedRange), normalizedRange(incoming)]
    .sort((left, right) => left.startMs - right.startMs || left.endMs - right.endMs);
  const merged: MarketHistoryRange[] = [];
  for (const range of ranges) {
    const previous = merged.at(-1);
    if (!previous || range.startMs > previous.endMs + 1) {
      merged.push({ ...range });
      continue;
    }
    previous.endMs = Math.max(previous.endMs, range.endMs);
  }
  return merged;
}

export function nextUncoveredHistoryRange(
  coverage: readonly MarketHistoryRange[],
  requested: MarketHistoryRange,
): MarketHistoryRange | null {
  const target = normalizedRange(requested);
  let cursor = target.startMs;
  for (const range of coverage.map(normalizedRange).sort((a, b) => a.startMs - b.startMs)) {
    if (range.endMs < cursor) continue;
    if (range.startMs > target.endMs) break;
    if (range.startMs > cursor) {
      return {
        startMs: cursor,
        endMs: Math.min(target.endMs, range.startMs - 1),
      };
    }
    cursor = Math.max(cursor, range.endMs + 1);
    if (cursor > target.endMs) return null;
  }
  return cursor <= target.endMs ? { startMs: cursor, endMs: target.endMs } : null;
}

export function coverageForHistoryPage(
  requested: MarketHistoryRange,
  payload: Pick<
    MarketHistoryPayload,
    "count" | "coverage" | "fallback" | "has_more" | "history_state" | "complete" | "retryable"
  >,
  direction: MarketHistoryPageDirection,
): MarketHistoryRange | null {
  const target = normalizedRange(requested);
  if (payload.coverage.ranges !== undefined) {
    // This compatibility helper can return only one contiguous range.
    const ranges = coverageRangesForHistoryPage(requested, payload, direction);
    return ranges.length === 1 ? ranges[0]! : null;
  }
  // Partial rows are useful for immediate rendering, but retryable means the
  // provider has not resolved all internal gaps. Never convert that response
  // into durable range coverage.
  if (payload.retryable === true) return null;
  const explicitlyResolved = payload.complete === true
    || payload.history_state === "exhausted";
  if (payload.fallback === true && !explicitlyResolved) return null;
  const earliestMs = payload.coverage.earliest_ms;
  const latestMs = payload.coverage.latest_ms;
  const pageIsExhaustive = payload.coverage.complete
    || payload.has_more === false
    || explicitlyResolved;
  if (pageIsExhaustive) return target;
  if (earliestMs === null || latestMs === null || payload.count === 0) return null;

  if (direction === "forward") {
    // Binance Funding returns the oldest page after startTime. Continue from
    // the page's latest sample toward the requested right edge.
    const coveredEnd = Math.max(target.startMs, Math.min(target.endMs, latestMs));
    return { startMs: target.startMs, endMs: coveredEnd };
  }

  // Binance OI history returns the newest page. Continue backward from the
  // page's earliest sample toward the requested left edge.
  const coveredStart = Math.max(target.startMs, Math.min(target.endMs, earliestMs));
  return { startMs: coveredStart, endMs: target.endMs };
}

export function coverageRangesForHistoryPage(
  requested: MarketHistoryRange,
  payload: Pick<MarketHistoryPayload,
    "count" | "coverage" | "fallback" | "has_more" | "history_state" | "complete" | "retryable"
  > & Pick<Partial<MarketHistoryPayload>, "excluded_ranges">,
  direction: MarketHistoryPageDirection,
): MarketHistoryRange[] {
  if (payload.coverage.ranges === undefined) {
    const legacy = coverageForHistoryPage(requested, payload, direction);
    return legacy ? [legacy] : [];
  }
  const target = normalizedRange(requested);
  // Explicit proof survives a different gap's failure. Exclusions resolve
  // acquisition, without presenting unavailable observations as market data.
  let ranges: MarketHistoryRange[] = [];
  for (const range of [...payload.coverage.ranges, ...(payload.excluded_ranges || [])]) {
    const startMs = Math.max(target.startMs, range.start_ms);
    const endMs = Math.min(target.endMs, range.end_ms);
    if (startMs <= endMs) ranges = mergeHistoryCoverage(ranges, { startMs, endMs });
  }
  return ranges;
}
