import { formatZoneOffset, formatZonedDateTimeInput } from "../../utils/zonedDateTimeInput.js";

/** Which clock Go to date reads and writes (PL-7). UTC stays the default. */
export type ChartTimeZoneMode = "utc" | "local";
export const CHART_TIME_ZONE_MODE_KEY = "candlescope.chartTime.zone.v1";

export function readChartTimeZoneMode(): ChartTimeZoneMode {
  try { return localStorage.getItem(CHART_TIME_ZONE_MODE_KEY) === "local" ? "local" : "utc"; } catch { return "utc"; }
}

export function writeChartTimeZoneMode(mode: ChartTimeZoneMode): void {
  try { localStorage.setItem(CHART_TIME_ZONE_MODE_KEY, mode); } catch { /* the choice just isn't remembered */ }
}

export function chartTimeZone(mode: ChartTimeZoneMode, localZone: string): string {
  return mode === "local" ? localZone : "UTC";
}

/** `2026-03-08 03:30:00 UTC−04:00`: the wall time in the zone and the offset in force then. */
export function chartTimeLabel(timeMs: number, zone: string): string {
  return `${formatZonedDateTimeInput(timeMs, zone).replace("T", " ")} ${formatZoneOffset(timeMs, zone)}`;
}
