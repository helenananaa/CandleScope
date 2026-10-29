/** Normalized OHLCV invariants, independent of transport, React and clocks. */
export interface KlineDomainIssue { field: string; reason: string }

export function validateKlineDomain(row: Record<string, unknown>): KlineDomainIssue | null {
  const time = row.time;
  if (typeof time !== "number" || !Number.isSafeInteger(time) || time < 0 || time > 10_000_000_000) {
    return { field: "time", reason: "expected non-negative unix seconds" };
  }
  for (const field of ["open", "high", "low", "close", "volume"] as const) {
    if (typeof row[field] !== "number" || !Number.isFinite(row[field])) {
      return { field, reason: "expected a finite normalized OHLCV number" };
    }
  }
  const { open, high, low, close, volume } = row as { open: number; high: number; low: number; close: number; volume: number };
  if (high < low || high < open || high < close) return { field: "high", reason: "must contain low, open and close" };
  if (low > open || low > close) return { field: "low", reason: "must contain open and close" };
  // Total volume is non-negative in all currently normalized units (base,
  // quote, contracts, shares). Signed flow belongs to delta/CVD fields.
  if (volume < 0) return { field: "volume", reason: "total volume must be non-negative" };
  if (row.is_closed !== undefined && typeof row.is_closed !== "boolean") {
    return { field: "is_closed", reason: "expected a boolean" };
  }
  for (const field of ["quote_volume", "trades", "taker_buy_base", "taker_buy_quote"]) {
    const value = row[field];
    if (value != null && (typeof value !== "number" || !Number.isFinite(value) || value < 0
      || (field === "trades" && !Number.isSafeInteger(value)))) {
      return { field, reason: "expected a non-negative normalized quantity" };
    }
  }
  return null;
}
