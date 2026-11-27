import { formatUtcDateTimeInput, parseUtcDateTimeInput } from "./utcDateTimeInput.js";

/**
 * `datetime-local` values in a named IANA time zone (PL-7). The browser's own
 * local-time conversion is never used, so the result does not depend on the
 * machine's zone and tests can pin any zone.
 *
 * Daylight saving makes wall time irregular:
 * - a gap (clocks go forward) has wall times that never happen. They resolve
 *   to the same wall time on the far side of the gap, e.g. 02:30 → 03:30 when
 *   New York moves from 02:00 EST to 03:00 EDT;
 * - an overlap (clocks go back) has wall times that happen twice. They resolve
 *   to the first one.
 * Both are reported, so the caller can tell the user what it did.
 */
export type ZonedDateTimeResolution = "exact" | "gap" | "overlap";

export interface ZonedDateTime {
  readonly timeMs: number;
  readonly resolution: ZonedDateTimeResolution;
}

const formatters = new Map<string, Intl.DateTimeFormat>();

function formatter(zone: string): Intl.DateTimeFormat {
  let cached = formatters.get(zone);
  if (!cached) {
    cached = new Intl.DateTimeFormat("en-US", {
      timeZone: zone,
      hourCycle: "h23",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    formatters.set(zone, cached);
  }
  return cached;
}

/** The zone's wall time at an instant, written as if it were UTC (milliseconds dropped). */
function wallClockAsUtc(timeMs: number, zone: string): number {
  const parts: Record<string, number> = {};
  for (const part of formatter(zone).formatToParts(new Date(timeMs))) {
    if (part.type !== "literal") parts[part.type] = Number(part.value);
  }
  return Date.UTC(parts.year!, parts.month! - 1, parts.day!, parts.hour! % 24, parts.minute!, parts.second!);
}

/** Offset of the zone from UTC at an instant, in milliseconds (east positive). */
export function zoneOffsetMs(timeMs: number, zone: string): number {
  return wallClockAsUtc(timeMs, zone) - Math.floor(timeMs / 1000) * 1000;
}

export function isValidTimeZone(zone: string): boolean {
  try {
    formatter(zone);
    return true;
  } catch {
    return false;
  }
}

/** The browser's zone, or UTC when it cannot say. */
export function localTimeZone(): string {
  try {
    const zone = new Intl.DateTimeFormat().resolvedOptions().timeZone;
    return zone && isValidTimeZone(zone) ? zone : "UTC";
  } catch {
    return "UTC";
  }
}

/** `UTC+08:00`, `UTC−04:00`, `UTC+05:45`, `UTC` for zero. */
export function formatZoneOffset(timeMs: number, zone: string): string {
  const offset = Math.round(zoneOffsetMs(timeMs, zone) / 60_000);
  if (offset === 0) return "UTC";
  const sign = offset > 0 ? "+" : "−";
  const minutes = Math.abs(offset);
  return `UTC${sign}${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

export function formatZonedDateTimeInput(timeMs: number | null, zone: string): string {
  if (timeMs === null || !Number.isSafeInteger(timeMs) || timeMs < 0) return "";
  if (zone === "UTC") return formatUtcDateTimeInput(timeMs);
  try {
    return formatUtcDateTimeInput(wallClockAsUtc(timeMs, zone));
  } catch {
    return "";
  }
}

/** The instant a wall time in `zone` names; null when the value is not a valid date and time. */
export function parseZonedDateTimeInput(value: string, zone: string): ZonedDateTime | null {
  const wall = parseUtcDateTimeInput(value);
  if (wall === null) return null;
  if (zone === "UTC") return { timeMs: wall, resolution: "exact" };
  try {
    // Every instant whose wall time could equal `wall` lies within a day of it.
    // The offsets in force a day either side bound the candidates.
    const before = zoneOffsetMs(wall - 86_400_000, zone);
    const after = zoneOffsetMs(wall + 86_400_000, zone);
    const candidates = [...new Set([before, after, zoneOffsetMs(wall, zone)])]
      .map((offset) => wall - offset)
      .filter((instant) => instant >= 0 && wallClockAsUtc(instant, zone) === wall)
      .sort((left, right) => left - right);
    if (candidates.length > 0) {
      return { timeMs: candidates[0]!, resolution: candidates.length > 1 ? "overlap" : "exact" };
    }
    // A gap: read the wall time with the offset in force before the clocks
    // jumped, which lands the same distance past the jump.
    const instant = wall - before;
    return instant >= 0 ? { timeMs: instant, resolution: "gap" } : null;
  } catch {
    return null;
  }
}
