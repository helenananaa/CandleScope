import { normalizeIndicatorRange } from "./indicatorRangeCoverage.js";
import type {
  IndicatorLine,
  IndicatorPartialSeedRange,
  IndicatorRange,
  IndicatorSeedState,
} from "./indicatorTypes.js";

const NO_PARTIAL_SEED: readonly IndicatorPartialSeedRange[] = Object.freeze([]);

/**
 * The bars of a `partial` range whose values precede convergence
 * (ADR-INDICATOR-001 §4). Range bar j sits `seedBars + j` bars after the
 * earliest stored bar, so values converge from j = warmupBars − seedBars.
 * Bars are counted from the returned points; points omitted for undefined
 * values can only move the end later, never earlier.
 */
export function partialSeedRangeFor(
  seed: IndicatorSeedState | null | undefined,
  range: IndicatorRange | null | undefined,
  lines: readonly IndicatorLine[],
): IndicatorPartialSeedRange | null {
  if (seed?.state !== "partial" || !range) return null;
  const provisionalBars = seed.warmupBars - seed.seedBars;
  if (provisionalBars <= 0) return null;
  const times = new Set<number>();
  for (const line of lines) {
    for (const point of line.data || []) {
      const time = Number(point.time);
      if (Number.isFinite(time) && time >= range.start && time <= range.end) {
        times.add(time);
      }
    }
  }
  const sorted = [...times].sort((left, right) => left - right);
  const end = sorted[provisionalBars - 1] ?? range.end;
  return {
    start: range.start,
    end,
    warmupBars: seed.warmupBars,
    seedBars: seed.seedBars,
  };
}

/**
 * Values inside `range` were just replaced, so earlier spans no longer
 * describe them; `incoming` (if any) does. Spans outside the range keep
 * describing values that were not recomputed.
 */
export function replacePartialSeedRanges(
  existing: readonly IndicatorPartialSeedRange[] | null | undefined,
  range: IndicatorRange,
  incoming: IndicatorPartialSeedRange | null,
): readonly IndicatorPartialSeedRange[] {
  const current = existing ?? NO_PARTIAL_SEED;
  if (!incoming && !current.some((item) => overlaps(item, range))) return current;
  const next: IndicatorPartialSeedRange[] = [];
  for (const item of current) {
    if (!overlaps(item, range)) {
      next.push(item);
      continue;
    }
    if (item.start < range.start) next.push({ ...item, end: range.start - 1 });
    if (item.end > range.end) next.push({ ...item, start: range.end + 1 });
  }
  if (incoming) next.push(incoming);
  return next.sort((left, right) => left.start - right.start);
}

/**
 * Spans after a payload is written. A snapshot replaces every value, a range
 * replacement the values inside its range, and a merge (live patch) changes
 * spans only when the payload reports a seed. The cache store and runtime
 * indicator state apply the same rule as they do for lines.
 */
export function updatePartialSeedRanges(
  existing: readonly IndicatorPartialSeedRange[] | null | undefined,
  write: "snapshot" | "replace-range" | "merge",
  rangeInput: unknown,
  seed: IndicatorSeedState | null | undefined,
  lines: readonly IndicatorLine[],
): readonly IndicatorPartialSeedRange[] {
  const range = normalizeIndicatorRange(rangeInput);
  const incoming = partialSeedRangeFor(seed, range, lines);
  if (write === "snapshot") return incoming ? [incoming] : NO_PARTIAL_SEED;
  if (!range || (write === "merge" && !seed)) return existing ?? NO_PARTIAL_SEED;
  return replacePartialSeedRanges(existing, range, incoming);
}

/** Sets or removes runtime partial-seed spans without changing identity needlessly. */
export function withPartialSeed<T extends { partialSeed?: readonly IndicatorPartialSeedRange[] }>(
  value: T,
  ranges: readonly IndicatorPartialSeedRange[],
): T {
  if (ranges.length > 0) {
    return value.partialSeed === ranges ? value : { ...value, partialSeed: ranges };
  }
  if (value.partialSeed === undefined) return value;
  const next = { ...value };
  delete next.partialSeed;
  return next;
}

export function partialSeedRangeAt(
  ranges: readonly IndicatorPartialSeedRange[] | null | undefined,
  time: number | null,
): IndicatorPartialSeedRange | null {
  if (!ranges || time === null) return null;
  return ranges.find((item) => time >= item.start && time <= item.end) ?? null;
}

function overlaps(item: IndicatorRange, range: IndicatorRange): boolean {
  return item.start <= range.end && item.end >= range.start;
}
