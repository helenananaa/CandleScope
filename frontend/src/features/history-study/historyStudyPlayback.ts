import { createIntervalTimeline } from "../../utils/intervalTimeline.js";
import { intervalTiles } from "../../utils/intervals.js";
import { projectStudyBars } from "./historyStudyProjection.js";
import { SeriesWindowStore } from "../market-data/window/seriesWindowStore.js";
import type { HistoryStudy } from "./historyStudyTypes.js";

function freeze<T>(value: T): T {
  if (value && typeof value === "object") {
    for (const child of Object.values(value)) freeze(child);
    Object.freeze(value);
  }
  return value;
}

/** The retained input never reaches chart/indicator consumers. Only this
 * independently owned prefix store does. A forward step admits the newly
 * closed rows; rewind replaces the revealed prefix before notifying React. */
export class HistoryStudyPlayback {
  readonly store: SeriesWindowStore;
  readonly input: HistoryStudy;
  private count = 0;
  private cursor = 0;
  private missing = new Set<number>();
  constructor(study: HistoryStudy, cursorMs: number) {
    const sourceSeries = study.sourceSeries ?? study.series;
    const timeline = createIntervalTimeline(sourceSeries.interval);
    const display = createIntervalTimeline(study.series.interval);
    if (!timeline || !display || !intervalTiles(sourceSeries.interval, study.series.interval)
      || JSON.stringify(Object.entries(sourceSeries).filter(([key]) => key !== "interval").sort())
        !== JSON.stringify(Object.entries(study.series).filter(([key]) => key !== "interval").sort())
      || !study.rows.length || study.rows.length > 5000) throw new Error("Invalid study input");
    let previous = -1;
    for (const row of study.rows) {
      if (!Number.isSafeInteger(row.time) || row.time <= previous
        || row.closeTimeMs !== timeline.next(row.time)! * 1000
        || ![row.open, row.high, row.low, row.close, row.volume].every(Number.isFinite)
        || row.is_closed !== true || row.volume < 0 || row.low > Math.min(row.open, row.close)
        || row.high < Math.max(row.open, row.close) || row.low > row.high) throw new Error("Invalid study candle");
      previous = row.time;
    }
    this.input = freeze(structuredClone(study));
    this.store = new SeriesWindowStore({ seriesKey: `history-study:${study.id}`, maxBars: 5000,
      intervalSeconds: display.spec.widthSeconds });
    this.seek(cursorMs);
  }
  get cursorMs() { return this.cursor; }
  get minimumMs() { return this.input.rows[0]!.time * 1000; }
  get maximumMs() { return this.input.rows.at(-1)!.closeTimeMs; }
  get missingBuckets() { return [...this.missing]; }
  seek(requestedMs: number): number {
    if (!Number.isSafeInteger(requestedMs)) throw new RangeError("Invalid study cursor");
    const cursor = Math.max(this.minimumMs, Math.min(this.maximumMs, requestedMs));
    const rows = this.input.rows;
    let low = 0, high = rows.length;
    while (low < high) {
      const mid = (low + high) >>> 1;
      if (rows[mid]!.closeTimeMs <= cursor) low = mid + 1;
      else high = mid;
    }
    this.cursor = cursor;
    if (low !== this.count) {
      const sourceInterval = (this.input.sourceSeries ?? this.input.series).interval;
      const displayInterval = this.input.series.interval;
      if (sourceInterval === displayInterval) {
        if (low < this.count) this.store.replace(rows.slice(0, low));
        else this.store.applyRange(rows.slice(this.count, low));
      } else if (low < this.count || this.count === 0) {
        const projection = projectStudyBars(rows.slice(0, low), sourceInterval, displayInterval);
        this.missing = new Set(projection.missingBuckets);
        this.store.replace(projection.rows);
      } else {
        // Rebuild only the affected display tail on ordinary forward steps.
        const timeline = createIntervalTimeline(displayInterval)!;
        const start = timeline.floor(rows[this.count - 1]!.time)!;
        let from = this.count - 1;
        while (from > 0 && rows[from - 1]!.time >= start) from -= 1;
        const projection = projectStudyBars(rows.slice(from, low), sourceInterval, displayInterval);
        for (const time of this.missing) if (time >= start) this.missing.delete(time);
        for (const time of projection.missingBuckets) this.missing.add(time);
        const previous = this.store.last();
        if (previous && previous.time >= start && projection.missingBuckets.includes(previous.time)) {
          this.store.replace([...this.store.snapshot().filter(row => row.time < start), ...projection.rows]);
        } else this.store.applyRange(projection.rows);
      }
    }
    this.count = low;
    return cursor;
  }
  stepTarget(direction: -1 | 1): number {
    const rows = this.input.rows;
    if (direction > 0) return rows[this.count]?.closeTimeMs ?? this.maximumMs;
    const current = rows[this.count - 1];
    // First move an intrabar cursor to the last committed close, then rewind.
    return current && current.closeTimeMs < this.cursor ? current.closeTimeMs
      : rows[this.count - 2]?.closeTimeMs ?? this.minimumMs;
  }
  step(direction: -1 | 1) { return this.seek(this.stepTarget(direction)); }
}
