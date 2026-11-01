import type { WindowChangedRange } from "./klineContracts.js";
import { mergeIndicatorWindowChangedRanges } from "./indicatorRangeRuntime.js";

const MAX_EXACT_CHANGED_RANGES = 512;

function boundRangesWithoutDroppingCoverage(
  ranges: WindowChangedRange[],
): WindowChangedRange[] {
  if (ranges.length <= MAX_EXACT_CHANGED_RANGES) return ranges;
  const boundaries: Array<{ index: number; gap: number }> = [];
  for (let index = 1; index < ranges.length; index += 1) {
    const previous = ranges[index - 1];
    const current = ranges[index];
    if (!previous || !current || previous.type !== current.type) continue;
    boundaries.push({
      index,
      gap: Math.max(0, Number(current.start) - Number(previous.end) - 1),
    });
  }
  boundaries.sort((left, right) => left.gap - right.gap || left.index - right.index);
  const joinedBoundaries = new Set(
    boundaries
      .slice(0, ranges.length - MAX_EXACT_CHANGED_RANGES)
      .map(({ index }) => index),
  );
  const bounded: WindowChangedRange[] = [];
  for (let index = 0; index < ranges.length; index += 1) {
    const range = ranges[index];
    if (!range) continue;
    const previous = bounded.at(-1);
    if (previous && joinedBoundaries.has(index) && previous.type === range.type) {
      previous.end = range.end;
    } else {
      bounded.push({ ...range });
    }
  }
  return bounded;
}

export interface IndicatorWindowCommitResult {
  deferred: boolean;
  lifecycleChanged: boolean;
  publish: boolean;
  ranges: WindowChangedRange[];
}

export interface IndicatorWindowCommitOptions {
  ownerToken?: string | null | undefined;
  pending?: boolean;
  epoch?: number | undefined;
}

interface IndicatorWindowSeriesState {
  owners: Set<string>;
  epoch?: number | undefined;
  ranges: WindowChangedRange[];
}

export class IndicatorWindowCommitBuffer {
  private readonly pending = new Map<string, IndicatorWindowSeriesState>();

  record(
    seriesKey: string,
    changedRanges: readonly WindowChangedRange[] = [],
    {
      ownerToken = null,
      pending = false,
      epoch,
    }: IndicatorWindowCommitOptions = {},
  ): IndicatorWindowCommitResult {
    const current = this.pending.get(seriesKey);
    const suppliedEpoch = Number.isSafeInteger(epoch) && Number(epoch) >= 0 ? epoch : undefined;
    if (suppliedEpoch !== undefined && current?.epoch !== undefined && suppliedEpoch < current.epoch) {
      return { deferred: current.owners.size > 0, lifecycleChanged: false, publish: false, ranges: [] };
    }
    const superseded = suppliedEpoch !== undefined && current?.epoch !== undefined && suppliedEpoch > current.epoch;
    // Feed epochs cancel their old requests and repair callbacks. Preserve the
    // accumulated changed ranges, but do not await owners that cannot settle.
    const owners = new Set(superseded ? [] : current?.owners || []);
    const activeEpoch = suppliedEpoch ?? current?.epoch;
    const normalizedOwner = String(ownerToken || "").trim();
    let lifecycleChanged = superseded && (current?.owners.size || 0) > 0;
    if (normalizedOwner) {
      if (pending) {
        lifecycleChanged = !owners.has(normalizedOwner) || lifecycleChanged;
        owners.add(normalizedOwner);
      } else {
        lifecycleChanged = owners.delete(normalizedOwner) || lifecycleChanged;
      }
    }
    const ranges = boundRangesWithoutDroppingCoverage(mergeIndicatorWindowChangedRanges(
      current?.ranges,
      changedRanges,
    ));
    if (owners.size > 0) {
      this.pending.set(seriesKey, { owners, ranges, epoch: activeEpoch });
      return { deferred: true, lifecycleChanged, publish: false, ranges };
    }
    if (activeEpoch === undefined) this.pending.delete(seriesKey);
    else this.pending.set(seriesKey, { owners, ranges: [], epoch: activeEpoch });
    return {
      deferred: false,
      lifecycleChanged,
      publish: ranges.length > 0,
      ranges,
    };
  }

  hasPending(seriesKey: string): boolean {
    return (this.pending.get(seriesKey)?.owners.size || 0) > 0;
  }

  hasOwner(seriesKey: string, ownerToken: string): boolean {
    return this.pending.get(seriesKey)?.owners.has(ownerToken) || false;
  }

  discard(seriesKey: string): void {
    this.pending.delete(seriesKey);
  }

  clear(): void {
    this.pending.clear();
  }

  snapshot(seriesKey: string): WindowChangedRange[] {
    return (this.pending.get(seriesKey)?.ranges || []).map((range) => ({ ...range }));
  }
}
