import { createIntervalTimeline } from "../../utils/intervalTimeline.js";
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
  constructor(study: HistoryStudy, cursorMs: number) {
    const timeline = createIntervalTimeline(study.series.interval);
    if (!timeline || !study.rows.length || study.rows.length > 5000) throw new Error("Invalid study input");
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
      intervalSeconds: timeline.spec.widthSeconds });
    this.seek(cursorMs);
  }
  get cursorMs() { return this.cursor; }
  get minimumMs() { return this.input.rows[0]!.time * 1000; }
  get maximumMs() { return this.input.rows.at(-1)!.closeTimeMs; }
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
    if (low < this.count) this.store.replace(rows.slice(0, low));
    else if (low > this.count) this.store.applyRange(rows.slice(this.count, low));
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
