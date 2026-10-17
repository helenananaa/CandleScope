import { sourceTimeFromAxisTime } from "./axisTime.js";
import type { LogicalRange } from "./chartRepresentationTypes.js";
import { addUtcCalendarMonths, createIntervalTimeline } from "../../utils/intervalTimeline.js";

export interface ViewportTimeRow { readonly time?: unknown }

const EMPTY_ROWS: readonly ViewportTimeRow[] = [];
const indexes = new WeakMap<readonly ViewportTimeRow[], WeakMap<readonly ViewportTimeRow[], readonly number[] | null>>();

/** Axis identity is elapsed view time; a synthetic leg's lineage can be much wider. */
function coordinates(rows: readonly ViewportTimeRow[], carriers: readonly ViewportTimeRow[]): readonly number[] | null {
  let byCarrier = indexes.get(rows);
  if (!byCarrier) { byCarrier = new WeakMap(); indexes.set(rows, byCarrier); }
  const cached = byCarrier.get(carriers);
  if (cached !== undefined) return cached;
  const times: number[] = [];
  for (const list of [rows, carriers]) for (const row of list) {
    const time = sourceTimeFromAxisTime(row.time);
    if (time === null || (times.length > 0 && time < times[times.length - 1]!)) {
      byCarrier.set(carriers, null);
      return null;
    }
    times.push(time);
  }
  byCarrier.set(carriers, times);
  return times;
}

/** Fractional mapping shared by period handoff, linked views and saved views.
 * The input projections are immutable. Index construction is once per projection;
 * pointer/viewport lookups do not scan the retained history.
 */
export function createViewportTimeScale(rows: readonly ViewportTimeRow[], sourceInterval?: unknown,
  carriers: readonly ViewportTimeRow[] = EMPTY_ROWS) {
  const times = coordinates(rows, carriers);
  if (!times?.length) return null;
  const last = times.length - 1;
  const timeline = createIntervalTimeline(sourceInterval);
  const edgeShift = (index: number, offset: number): number | null => {
    const open = times[index]!;
    if (timeline?.spec.monthCount) return addUtcCalendarMonths(open, offset * timeline.spec.monthCount);
    const neighbor = times[index === 0 ? 1 : index - 1];
    const width = timeline?.spec.widthSeconds
      ?? (timeline?.spec.weekCount ? timeline.spec.weekCount * 604800 : null)
      ?? (neighbor === undefined ? null : Math.abs(open - neighbor));
    return width && width > 0 ? open + offset * width : null;
  };
  const timeAt = (position: number): number | null => {
    if (!Number.isFinite(position)) return null;
    const integer = Math.floor(position), fraction = position - integer;
    if (integer >= 0 && integer < last) {
      return times[integer]! + fraction * (times[integer + 1]! - times[integer]!);
    }
    const anchor = integer < 0 ? 0 : last;
    if (position === anchor) return times[anchor]!;
    const left = edgeShift(anchor, integer - anchor), right = edgeShift(anchor, integer - anchor + 1);
    return left !== null && right !== null && right > left ? left + fraction * (right - left) : null;
  };
  const logicalAt = (time: number, edge: "from" | "to"): number | null => {
    if (!Number.isFinite(time)) return null;
    if (time < times[0]! || time > times[last]!) {
      const index = time < times[0]! ? 0 : last, open = times[index]!;
      if (timeline?.spec.monthCount) {
        const target = new Date(time * 1000), origin = new Date(open * 1000);
        const months = (target.getUTCFullYear() - origin.getUTCFullYear()) * 12
          + target.getUTCMonth() - origin.getUTCMonth();
        const offset = Math.floor(months / timeline.spec.monthCount);
        const left = edgeShift(index, offset), right = edgeShift(index, offset + 1);
        return left !== null && right !== null && right > left ? index + offset + (time - left) / (right - left) : null;
      }
      const next = edgeShift(index, 1);
      return next !== null && next > open ? index + (time - open) / (next - open) : null;
    }
    let low = 0, high = times.length;
    while (low < high) {
      const middle = (low + high) >>> 1;
      if (times[middle]! < time || (edge === "to" && times[middle] === time)) low = middle + 1;
      else high = middle;
    }
    if (edge === "to" && low > 0 && times[low - 1] === time) return low - 1;
    if (times[low] === time) return low;
    if (low === 0 || low > last) return null;
    return low - 1 + (time - times[low - 1]!) / (times[low]! - times[low - 1]!);
  };
  return {
    sourceRange(range: LogicalRange): LogicalRange | null {
      const from = timeAt(range.from), to = timeAt(range.to);
      return from !== null && to !== null && to >= from ? { from, to } : null;
    },
    logicalRange(range: LogicalRange): LogicalRange | null {
      const from = logicalAt(range.from, "from"), to = logicalAt(range.to, "to");
      return from !== null && to !== null && to > from ? { from, to } : null;
    },
  };
}
