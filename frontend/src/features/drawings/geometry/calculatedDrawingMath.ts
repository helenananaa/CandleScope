/**
 * Pure calculations behind the calculated drawings (PL-3).
 *
 * Every function takes the bars the chart currently shows. A replay chart only
 * shows revealed bars, so nothing here can read past the reveal boundary.
 *
 * Bars are counted by position, never by clock time: a market closure (a
 * weekend, an overnight session break) leaves no bars, and nothing here fills
 * or interpolates it. Whitespace rows without prices are skipped.
 */

export interface CalculationBar {
  /** Position among the priced bars, starting at 0. */
  readonly index: number;
  readonly time: number;
  readonly high: number;
  readonly low: number;
  readonly close: number;
  /** 0 when the row has no usable volume. */
  readonly volume: number;
}

interface BarLike {
  readonly [field: string]: unknown;
  readonly time?: unknown;
  readonly high?: unknown;
  readonly low?: unknown;
  readonly close?: unknown;
  readonly volume?: unknown;
}

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

/** Priced bars in time order. Rows with a non-numeric time or missing prices are left out. */
export function calculationBars(rows: readonly BarLike[]): readonly CalculationBar[] {
  const bars: CalculationBar[] = [];
  let previousTime = Number.NEGATIVE_INFINITY;
  for (const row of rows) {
    const { time, high, low, close } = row;
    if (!finite(time) || !finite(high) || !finite(low) || !finite(close)) continue;
    // Series data is sorted; a repeated or older time is a malformed row, not a new bar.
    if (time <= previousTime) continue;
    previousTime = time;
    const volume = finite(row.volume) && row.volume > 0 ? row.volume : 0;
    bars.push({ index: bars.length, time, high: Math.max(high, low), low: Math.min(high, low), close, volume });
  }
  return bars;
}

/** First bar at or after `time`, or -1. */
export function barIndexAtOrAfter(bars: readonly CalculationBar[], time: number): number {
  let low = 0;
  let high = bars.length;
  while (low < high) {
    const middle = (low + high) >> 1;
    if (bars[middle]!.time < time) low = middle + 1;
    else high = middle;
  }
  return low < bars.length ? low : -1;
}

/** Last bar at or before `time`, or -1. */
export function barIndexAtOrBefore(bars: readonly CalculationBar[], time: number): number {
  const after = barIndexAtOrAfter(bars, time);
  if (after === -1) return bars.length - 1;
  return bars[after]!.time === time ? after : after - 1;
}

/** Bars whose time lies between the two anchors, in either order. */
export function barsBetween(
  bars: readonly CalculationBar[],
  firstTime: number,
  secondTime: number,
): readonly CalculationBar[] {
  const start = barIndexAtOrAfter(bars, Math.min(firstTime, secondTime));
  const end = barIndexAtOrBefore(bars, Math.max(firstTime, secondTime));
  return start === -1 || end < start ? [] : bars.slice(start, end + 1);
}

// ── Fibonacci extension ──

export const DEFAULT_FIB_EXTENSION_RATIOS: readonly number[] = Object.freeze([
  0, 0.618, 1, 1.272, 1.618, 2, 2.618,
]);

export interface FibExtensionLevel {
  readonly ratio: number;
  readonly price: number;
}

/** Levels projected from C by the A→B move: price = C + (B − A) × ratio. */
export function fibExtensionLevels(
  a: number,
  b: number,
  c: number,
  ratios: readonly number[] = DEFAULT_FIB_EXTENSION_RATIOS,
): readonly FibExtensionLevel[] {
  if (!finite(a) || !finite(b) || !finite(c)) return [];
  const move = b - a;
  return Object.freeze(ratios.filter(finite).map((ratio) => Object.freeze({ ratio, price: c + move * ratio })));
}

// ── Anchored VWAP ──

export interface VwapPoint {
  readonly time: number;
  readonly price: number;
}

/**
 * Volume-weighted average of the typical price (H + L + C) / 3 from the first
 * bar at or after the anchor to the last bar on the chart. Bars without
 * volume add nothing; until some volume has traded there is no value.
 */
export function anchoredVwap(bars: readonly CalculationBar[], anchorTime: number): readonly VwapPoint[] {
  if (!finite(anchorTime)) return [];
  const start = barIndexAtOrAfter(bars, anchorTime);
  if (start === -1) return [];
  const points: VwapPoint[] = [];
  let weighted = 0;
  let volume = 0;
  for (let index = start; index < bars.length; index += 1) {
    const bar = bars[index]!;
    if (bar.volume > 0) {
      weighted += ((bar.high + bar.low + bar.close) / 3) * bar.volume;
      volume += bar.volume;
    }
    if (volume > 0) points.push(Object.freeze({ time: bar.time, price: weighted / volume }));
  }
  return Object.freeze(points);
}

// ── Fixed-range volume profile ──

export const DEFAULT_VOLUME_PROFILE_ROWS = 24;
export const MIN_VOLUME_PROFILE_ROWS = 4;
export const MAX_VOLUME_PROFILE_ROWS = 200;
const VALUE_AREA_SHARE = 0.7;

export interface VolumeProfileRow {
  readonly low: number;
  readonly high: number;
  readonly volume: number;
  readonly inValueArea: boolean;
}

export interface VolumeProfile {
  readonly startTime: number;
  readonly endTime: number;
  readonly low: number;
  readonly high: number;
  readonly rows: readonly VolumeProfileRow[];
  /** Row with the most volume (point of control). */
  readonly pocIndex: number;
  readonly totalVolume: number;
  readonly barCount: number;
  /**
   * Always true here: built from OHLCV bars, each bar's volume is spread evenly
   * over its high–low range because the trades inside a bar are not known.
   */
  readonly estimated: true;
}

/** Profile of the bars between two anchors; null when there is no priced, traded bar. */
export function fixedRangeVolumeProfile(
  bars: readonly CalculationBar[],
  firstTime: number,
  secondTime: number,
  rowCount = DEFAULT_VOLUME_PROFILE_ROWS,
): VolumeProfile | null {
  if (!finite(firstTime) || !finite(secondTime)) return null;
  const range = barsBetween(bars, firstTime, secondTime);
  const traded = range.filter((bar) => bar.volume > 0);
  if (traded.length === 0) return null;
  const count = Math.min(MAX_VOLUME_PROFILE_ROWS, Math.max(MIN_VOLUME_PROFILE_ROWS, Math.round(finite(rowCount) ? rowCount : DEFAULT_VOLUME_PROFILE_ROWS)));
  let low = Number.POSITIVE_INFINITY;
  let high = Number.NEGATIVE_INFINITY;
  for (const bar of traded) {
    low = Math.min(low, bar.low);
    high = Math.max(high, bar.high);
  }
  // A flat range still needs a visible row height.
  const span = high > low ? high - low : Math.max(Math.abs(high) * 1e-6, 1e-9);
  if (!(high > low)) {
    low -= span / 2;
    high += span / 2;
  }
  const step = (high - low) / count;
  const volumes = new Float64Array(count);
  const rowOf = (price: number) => Math.min(count - 1, Math.max(0, Math.floor((price - low) / step)));
  for (const bar of traded) {
    if (bar.high <= bar.low) {
      volumes[rowOf(bar.close)]! += bar.volume;
      continue;
    }
    const first = rowOf(bar.low);
    const last = rowOf(bar.high);
    const perPrice = bar.volume / (bar.high - bar.low);
    for (let row = first; row <= last; row += 1) {
      const rowLow = low + row * step;
      const overlap = Math.min(bar.high, rowLow + step) - Math.max(bar.low, rowLow);
      if (overlap > 0) volumes[row]! += overlap * perPrice;
    }
  }
  let pocIndex = 0;
  let totalVolume = 0;
  for (let row = 0; row < count; row += 1) {
    totalVolume += volumes[row]!;
    if (volumes[row]! > volumes[pocIndex]!) pocIndex = row;
  }
  // Value area: grow from the POC toward the larger neighbour until 70 % is covered.
  const inValueArea = new Uint8Array(count);
  inValueArea[pocIndex] = 1;
  let covered = volumes[pocIndex]!;
  let below = pocIndex - 1;
  let above = pocIndex + 1;
  while (covered < totalVolume * VALUE_AREA_SHARE && (below >= 0 || above < count)) {
    const belowVolume = below >= 0 ? volumes[below]! : -1;
    const aboveVolume = above < count ? volumes[above]! : -1;
    if (aboveVolume >= belowVolume) {
      inValueArea[above] = 1;
      covered += aboveVolume;
      above += 1;
    } else {
      inValueArea[below] = 1;
      covered += belowVolume;
      below -= 1;
    }
  }
  const rows: VolumeProfileRow[] = [];
  for (let row = 0; row < count; row += 1) {
    rows.push(Object.freeze({
      low: low + row * step,
      high: row === count - 1 ? high : low + (row + 1) * step,
      volume: volumes[row]!,
      inValueArea: inValueArea[row] === 1,
    }));
  }
  return Object.freeze({
    startTime: range[0]!.time,
    endTime: range[range.length - 1]!.time,
    low,
    high,
    rows: Object.freeze(rows),
    pocIndex,
    totalVolume,
    barCount: range.length,
    estimated: true as const,
  });
}

// ── Regression channel ──

export const DEFAULT_REGRESSION_DEVIATION = 2;
export const MIN_REGRESSION_DEVIATION = 0.1;
export const MAX_REGRESSION_DEVIATION = 10;

export interface RegressionChannel {
  readonly startTime: number;
  readonly endTime: number;
  /** Fitted close at the first and last bar. */
  readonly startPrice: number;
  readonly endPrice: number;
  /** Price per bar (not per second). */
  readonly slope: number;
  readonly standardDeviation: number;
  /** Rail distance from the fitted line: deviation × standard deviation. */
  readonly offset: number;
  readonly barCount: number;
}

/**
 * Least-squares line through the closes of the bars between the anchors, with
 * x = bar position. Gaps between sessions therefore do not bend the slope.
 */
export function regressionChannel(
  bars: readonly CalculationBar[],
  firstTime: number,
  secondTime: number,
  deviation = DEFAULT_REGRESSION_DEVIATION,
): RegressionChannel | null {
  if (!finite(firstTime) || !finite(secondTime)) return null;
  const range = barsBetween(bars, firstTime, secondTime);
  const n = range.length;
  if (n < 2) return null;
  let sumX = 0;
  let sumY = 0;
  for (let k = 0; k < n; k += 1) {
    sumX += k;
    sumY += range[k]!.close;
  }
  const meanX = sumX / n;
  const meanY = sumY / n;
  let covariance = 0;
  let varianceX = 0;
  for (let k = 0; k < n; k += 1) {
    covariance += (k - meanX) * (range[k]!.close - meanY);
    varianceX += (k - meanX) ** 2;
  }
  const slope = varianceX > 0 ? covariance / varianceX : 0;
  const intercept = meanY - slope * meanX;
  let squared = 0;
  for (let k = 0; k < n; k += 1) {
    squared += (range[k]!.close - (intercept + slope * k)) ** 2;
  }
  const standardDeviation = Math.sqrt(squared / n);
  const width = finite(deviation) && deviation >= 0 ? deviation : DEFAULT_REGRESSION_DEVIATION;
  return Object.freeze({
    startTime: range[0]!.time,
    endTime: range[n - 1]!.time,
    startPrice: intercept,
    endPrice: intercept + slope * (n - 1),
    slope,
    standardDeviation,
    offset: width * standardDeviation,
    barCount: n,
  });
}
