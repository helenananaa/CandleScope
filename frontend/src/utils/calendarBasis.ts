import rules from "../../data/calendar-v1.json";

export type CalendarZone = keyof typeof rules.zones;
export type CalendarUnit = "d" | "w" | "M";
export const CALENDAR_ZONES = Object.keys(rules.zones) as CalendarZone[];
export const CALENDAR_INTERVAL_RE = /^([1-9]\d*)([dwM])~c1~(UTC|Asia\/Shanghai|America\/New_York)$/;
const DAY = 86400;
const EPOCH_MONTH = 1970 * 12;

export function calendarParts(value: string): { amount: number; unit: CalendarUnit; zone: CalendarZone } | null {
  const match = CALENDAR_INTERVAL_RE.exec(value.trim());
  if (!match) return null;
  const amount = Number(match[1]), unit = match[2] as CalendarUnit;
  if (amount > { d: 366, w: 52, M: 12 }[unit]) return null;
  return { amount, unit, zone: match[3] as CalendarZone };
}

function offset(time: number, zone: CalendarZone): number | null {
  const rows = rules.zones[zone];
  if (!Number.isFinite(time) || time < rows[0]![0]! || time >= 13632624000) return null;
  let low = 0, high = rows.length;
  while (low + 1 < high) {
    const middle = Math.floor((low + high) / 2);
    if (rows[middle]![0]! <= time) low = middle; else high = middle;
  }
  return rows[low]![1]!;
}

export function calendarWallToUtc(wall: number, zone: CalendarZone): number | null {
  const offsets = new Set(rules.zones[zone].map(row => row[1]!));
  const candidates = [...offsets].map(value => wall - value).filter(time => time + (offset(time, zone) ?? NaN) === wall);
  return candidates.length === 1 ? candidates[0]! : null;
}

function wallDate(time: number, zone: CalendarZone): Date | null {
  const delta = offset(time, zone);
  return delta === null ? null : new Date((time + delta) * 1000);
}

export function calendarFloor(time: number, count: number, unit: CalendarUnit, zone: CalendarZone): number | null {
  const date = wallDate(time, zone);
  if (!date) return null;
  let wall: number;
  if (unit === "M") {
    const month = date.getUTCFullYear() * 12 + date.getUTCMonth();
    const first = EPOCH_MONTH + Math.floor((month - EPOCH_MONTH) / count) * count;
    wall = Date.UTC(Math.floor(first / 12), first % 12, 1) / 1000;
  } else {
    const day = Math.floor(date.getTime() / 1000 / DAY);
    const width = count * (unit === "w" ? 7 : 1), anchor = unit === "w" ? 4 : 0;
    wall = (anchor + Math.floor((day - anchor) / width) * width) * DAY;
  }
  return calendarWallToUtc(wall, zone);
}

export function calendarShift(time: number, count: number, unit: CalendarUnit, zone: CalendarZone): number | null {
  const date = wallDate(time, zone);
  if (!date) return null;
  if (unit === "M") date.setUTCMonth(date.getUTCMonth() + count, 1);
  else date.setUTCDate(date.getUTCDate() + count * (unit === "w" ? 7 : 1));
  date.setUTCHours(0, 0, 0, 0);
  return calendarWallToUtc(date.getTime() / 1000, zone);
}
