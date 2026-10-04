/** Seconds without live data before the age badge appears. */
export const DATA_AGE_VISIBLE_SECONDS = 10;
/** Seconds without live data before the cell is marked stale. */
export const DATA_STALE_SECONDS = 60;

/** Window deltas that mean new data reached the chart. */
export const LIVE_DELTA_TYPES: ReadonlySet<string> = new Set(["tick", "append", "replace"]);

export function formatDataAge(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h`;
}

export type DataAgeLevel = "fresh" | "aging" | "stale";

export function dataAgeLevel(seconds: number): DataAgeLevel {
  if (seconds >= DATA_STALE_SECONDS) return "stale";
  if (seconds >= DATA_AGE_VISIBLE_SECONDS) return "aging";
  return "fresh";
}
