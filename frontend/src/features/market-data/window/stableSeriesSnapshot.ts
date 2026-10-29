import type { KlineBar } from "../marketDataTypes.js";
import type { SeriesWindowView, WindowCommitState } from "./seriesWindowView.js";

export interface SeriesCaptureOptions { limit?: number; from?: number; to?: number }
export type SeriesCapturePolicy = "exact" | "forming-preview" | "range";
export interface StableSeriesSnapshot {
  readonly state: WindowCommitState | undefined;
  readonly version: number;
  readonly rows: readonly Readonly<KlineBar>[];
  isCurrent(policy?: SeriesCapturePolicy): boolean;
}

function freezeClone<T>(value: T): T {
  if (value && typeof value === "object") {
    const clone = structuredClone(value);
    const freeze = (item: object) => {
      const children: unknown[] = Object.values(item);
      for (const child of children) if (child && typeof child === "object") freeze(child);
      Object.freeze(item);
    };
    freeze(clone);
    return clone;
  }
  return value;
}

/** Owned readers supply the epoch/entry fence. Mutable replay/static readers
 * use a deep copy and the stricter exact-version policy. No subscription is
 * retained by a capture, so abandoned asynchronous work cannot leak listeners. */
export function createStableSeriesSnapshot(
  source: SeriesWindowView,
  options: SeriesCaptureOptions = {},
  ownsSource: () => boolean = () => true,
  immutableRows = false,
): StableSeriesSnapshot {
  const version = source.version, axisRevision = source.axisRevision, count = source.barCount;
  let selected = source.snapshot();
  if (options.from !== undefined || options.to !== undefined) {
    selected = selected.filter(row => (options.from === undefined || Number(row.time) >= options.from)
      && (options.to === undefined || Number(row.time) <= options.to));
  }
  const limit = options.limit === undefined ? selected.length : Math.max(1, Math.floor(options.limit));
  const rows = Object.freeze(selected.slice(-limit).map(row => immutableRows ? row : freezeClone(row)));
  return Object.freeze({
    state: source.commitState,
    version,
    rows,
    isCurrent(policy: SeriesCapturePolicy = "exact") {
      if (!ownsSource()) return false;
      if (source.version === version) return true;
      if (!immutableRows || policy === "exact" || !rows.length) return false;
      const first = rows[0]!, last = rows.at(-1)!;
      const start = source.indexOfTime(first.time), end = source.indexOfTime(last.time);
      if (start < 0 || end - start !== rows.length - 1) return false;
      if (policy === "forming-preview" && (source.axisRevision !== axisRevision || source.barCount !== count
        || source.last()?.time !== last.time || last.is_closed === true || source.last()?.is_closed === true)) return false;
      const stableCount = policy === "forming-preview" ? rows.length - 1 : rows.length;
      for (let index = 0; index < stableCount; index += 1) {
        if (source.getByTime(rows[index]!.time) !== rows[index]) return false;
      }
      return true;
    },
  });
}

export function captureStableSeries(source: SeriesWindowView, options?: SeriesCaptureOptions): StableSeriesSnapshot {
  return source.capture?.(options) ?? createStableSeriesSnapshot(source, options);
}
