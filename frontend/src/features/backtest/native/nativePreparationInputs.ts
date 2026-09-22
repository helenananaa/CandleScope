export interface NativePreparationContext {
  exchange: string; market_type: string; symbol: string; interval: string;
  binding_symbol: string; warmup_bars?: number | undefined;
}

export function restorePreparationDate(value: unknown, fallback: string): string {
  // Empty is an unfinished edit, not permission to substitute another range.
  if (value === "") return "";
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return fallback;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value ? value : fallback;
}

export function restorePreparationContexts(value: unknown): NativePreparationContext[] {
  if (!Array.isArray(value)) return [];
  const candidates: unknown[] = value;
  return candidates.slice(0, 16).filter((item): item is NativePreparationContext => {
    if (item === null || typeof item !== "object") return false;
    const row = item as Record<string, unknown>;
    return ["exchange", "market_type", "symbol", "interval", "binding_symbol"].every((key) => typeof row[key] === "string")
      && (row.warmup_bars === undefined || (typeof row.warmup_bars === "number" && Number.isInteger(row.warmup_bars)
        && row.warmup_bars >= 0 && row.warmup_bars <= 5000));
  });
}
