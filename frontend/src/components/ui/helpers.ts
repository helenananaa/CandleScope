// Pure helpers for the UI primitives (kept apart so component files only export components).
import type { ButtonProps } from "./Button.js";

export function buttonClassName({ variant = "secondary", size = "md", fullWidth = false, className }: Pick<ButtonProps, "variant" | "size" | "fullWidth" | "className">): string {
  return [
    "ui-btn",
    variant === "secondary" ? null : `ui-btn-${variant}`,
    size === "sm" ? "ui-btn-sm" : null,
    fullWidth ? "ui-btn-block" : null,
    className,
  ].filter(Boolean).join(" ");
}

/**
 * Index to move to for an arrow, Home or End key in a one-dimensional group, skipping
 * disabled items and wrapping around; null for other keys.
 */
export function choiceKeyTarget(key: string, index: number, disabled: readonly boolean[]): number | null {
  const count = disabled.length;
  if (!count) return null;
  const step = key === "ArrowRight" || key === "ArrowDown" ? 1 : key === "ArrowLeft" || key === "ArrowUp" ? -1 : 0;
  let start: number;
  let direction: number;
  if (step) { start = index + step; direction = step; }
  else if (key === "Home") { start = 0; direction = 1; }
  else if (key === "End") { start = count - 1; direction = -1; }
  else return null;
  for (let i = 0; i < count; i++) {
    const candidate = (((start + i * direction) % count) + count) % count;
    if (!disabled[candidate]) return candidate;
  }
  return null;
}

export const tabId = (base: string, value: string) => `${base}-tab-${value}`;
export const tabPanelId = (base: string, value: string) => `${base}-panel-${value}`;

const pad = (value: number, length = 2) => String(value).padStart(length, "0");

/** `datetime-local` value for an epoch time, in UTC or the browser's time zone. */
export function toDateTimeInputValue(epochMs: number | null, utc: boolean, seconds = false): string {
  if (epochMs == null || !Number.isFinite(epochMs)) return "";
  const date = new Date(epochMs);
  const parts = utc
    ? [date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate(), date.getUTCHours(), date.getUTCMinutes(), date.getUTCSeconds()]
    : [date.getFullYear(), date.getMonth() + 1, date.getDate(), date.getHours(), date.getMinutes(), date.getSeconds()];
  const [y = 0, mo = 1, d = 1, h = 0, mi = 0, s = 0] = parts;
  return `${pad(y, 4)}-${pad(mo)}-${pad(d)}T${pad(h)}:${pad(mi)}${seconds ? `:${pad(s)}` : ""}`;
}

/** Epoch time for a `datetime-local` value, or null when it is empty or invalid. */
export function fromDateTimeInputValue(value: string, utc: boolean): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(value.trim());
  if (!match) return null;
  const [y, mo, d, h, mi, s] = match.slice(1).map((part) => Number(part ?? 0)) as [number, number, number, number, number, number];
  const time = utc ? Date.UTC(y, mo - 1, d, h, mi, s) : new Date(y, mo - 1, d, h, mi, s).getTime();
  const check = new Date(time);
  const sameDay = utc ? check.getUTCDate() === d && check.getUTCMonth() === mo - 1 : check.getDate() === d && check.getMonth() === mo - 1;
  return Number.isFinite(time) && sameDay ? time : null;
}

/** The same time as text the user reads and types: `2026-01-02 03:04` (or with `:05` seconds). */
export function toDateTimeText(epochMs: number | null, utc: boolean, seconds = false): string {
  return toDateTimeInputValue(epochMs, utc, seconds).replace("T", " ");
}

/**
 * Epoch time for typed text, or null when it is empty or invalid. Accepts `-` or `/` between the
 * date parts, a space or `T` before the time, single-digit month, day and hour, optional seconds,
 * and a date on its own (midnight).
 */
export function fromDateTimeText(text: string, utc: boolean): number | null {
  const match = /^(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[ T]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$/.exec(text.trim());
  if (!match) return null;
  const [y = "", mo = "", d = "", h = "0", mi = "0", s = "0"] = match.slice(1).map((part) => part ?? undefined);
  if (Number(h) > 23 || Number(mi) > 59 || Number(s) > 59) return null;
  const pad = (value: string) => value.padStart(2, "0");
  return fromDateTimeInputValue(`${y}-${pad(mo)}-${pad(d)}T${pad(h)}:${pad(mi)}:${pad(s)}`, utc);
}
