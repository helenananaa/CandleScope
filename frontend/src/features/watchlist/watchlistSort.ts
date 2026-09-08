import { parseSymbolKey } from "../../utils/symbolKey.js";
import type { WatchlistPriceSnapshot } from "./watchlistPriceStore.js";
import type { SubscriptionTier, WatchlistGroup } from "./watchlistTypes.js";

export type WatchlistSortColumn = "symbol" | "price" | "change" | "changePct";
export type WatchlistSortDirection = "asc" | "desc";

/** Apply one quote snapshot to each list; subsequent ticks never move a row. */
export function sortWatchlists(
  groups: WatchlistGroup[],
  column: WatchlistSortColumn,
  direction: WatchlistSortDirection,
  prices: WatchlistPriceSnapshot,
  tiers?: Record<string, SubscriptionTier>,
): WatchlistGroup[] {
  const value = (key: string): string | number | undefined => {
    if (column === "symbol") return parseSymbolKey(key).symbol;
    const tick = prices[key];
    if (tiers?.[key] === "none" || typeof tick?.price !== "number" || !Number.isFinite(tick.price)) return undefined;
    const result = column === "price" ? tick.price
      : column === "change" ? (tick.daily_change ?? tick.price - (tick.open ?? tick.price))
        : (tick.daily_change_pct ?? tick.change_pct ?? 0);
    return Number.isFinite(result) ? result : undefined;
  };
  return groups.map((group) => ({
    ...group,
    symbols: group.symbols.map((key, index) => ({ key, index, value: value(key) })).sort((a, b) => {
      // Missing quotes stay last in either direction; equal values retain manual order.
      if (a.value === undefined) return b.value === undefined ? a.index - b.index : 1;
      if (b.value === undefined) return -1;
      const difference = typeof a.value === "string" && typeof b.value === "string"
        ? a.value.localeCompare(b.value) : Number(a.value) - Number(b.value);
      return (direction === "asc" ? difference : -difference) || a.index - b.index;
    }).map(({ key }) => key),
  }));
}
