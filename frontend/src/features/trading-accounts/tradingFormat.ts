import { getDateTimeLocale, getNumberLocale } from "../../i18n/index.js";

export function formatAmount(value: string | number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return number.toLocaleString(getNumberLocale(), {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatSigned(value: string | number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  const text = formatAmount(Math.abs(number), digits);
  if (number > 0) return `+${text}`;
  if (number < 0) return `−${text}`;
  return text;
}

/** Prices keep their own precision; only grouping is localized. */
export function formatPrice(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  const text = String(value);
  const decimals = text.includes(".") ? Math.min(8, text.split(".")[1]!.length) : 0;
  return number.toLocaleString(getNumberLocale(), {
    minimumFractionDigits: Math.min(decimals, 2),
    maximumFractionDigits: Math.max(decimals, 2),
  });
}

export function formatQty(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return number.toLocaleString(getNumberLocale(), { maximumFractionDigits: 8 });
}

export function formatDateTime(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  return new Date(ms).toLocaleString(getDateTimeLocale(), {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDuration(fromMs: number, toMs: number): string {
  const minutes = Math.max(0, Math.round((toMs - fromMs) / 60_000));
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours}h ${minutes % 60}m`;
  return `${Math.floor(hours / 24)}d ${hours % 24}h`;
}

/** A 0–1 ratio as a whole percentage. */
export function formatPercent(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return number.toLocaleString(getNumberLocale(), { style: "percent", maximumFractionDigits: 0 });
}

/** An R multiple with sign, e.g. +1.25R. */
export function formatR(value: string | number | null | undefined): string {
  const text = formatSigned(value);
  return text === "—" ? text : `${text}R`;
}

/** The backend sends no profit factor without losses: ∞ if there was profit. */
export function formatProfitFactor(stats: { profitFactor: string | null; grossProfit: string }): string {
  if (stats.profitFactor !== null) return formatAmount(stats.profitFactor);
  return Number(stats.grossProfit) > 0 ? "∞" : "—";
}

function rBound(value: string): string {
  const number = Number(value);
  return number < 0 ? `−${Math.abs(number)}` : String(number);
}

/** R bucket label; open-ended buckets have a null bound. */
export function formatRBucket(bucket: { fromR: string | null; toR: string | null }): string {
  if (bucket.fromR === null) return `≤ ${rBound(bucket.toR ?? "0")}R`;
  if (bucket.toR === null) return `≥ ${rBound(bucket.fromR)}R`;
  return `${rBound(bucket.fromR)} … ${rBound(bucket.toR)}R`;
}

export function pnlTone(value: string | number | null | undefined): "up" | "down" | "flat" {
  const number = Number(value);
  if (!Number.isFinite(number) || number === 0) return "flat";
  return number > 0 ? "up" : "down";
}

/** Canvas series need concrete colors; read them from the design tokens. */
export function tokenColor(name: string, fallback: string): string {
  if (typeof document === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}
