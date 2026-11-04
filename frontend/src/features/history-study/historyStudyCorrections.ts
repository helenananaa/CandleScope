import type { KlineBar } from "../market-data/marketDataTypes.js";
import type { StudyBar } from "./historyStudyTypes.js";

/** Durable JSON may reorder object keys. Compare market facts and field
 * availability, not serialization order or later live candles outside the study. */
export function studyInputHasChanged(saved: readonly StudyBar[], current: readonly KlineBar[]): boolean {
  if (!saved.length) return false;
  const byTime = new Map(saved.map(row => [row.time, row]));
  return current.some(row => {
    if (row.time < saved[0]!.time || row.time > saved.at(-1)!.time || row.is_closed === false) return false;
    const original = byTime.get(row.time);
    if (!original) return true;
    if (["open", "high", "low", "close", "volume", "quote_volume", "trades", "taker_buy_base", "taker_buy_quote"]
      .some(key => (original[key] ?? null) !== (row[key] ?? null))) return true;
    const before = original.order_flow as Record<string, unknown> | null | undefined;
    const after = row.order_flow;
    return ["taker_sell_base", "volume_delta_base", "taker_buy_ratio_base", "cvd_contribution_base"]
      .some(key => (before?.[key] ?? null) !== (after?.[key] ?? null));
  });
}
