import type { OrderBookLevel } from "./orderBookTypes.js";

export interface DisplayOrderBookLevel {
  slot: number;
  price: number;
  quantity: number;
  cumulative: number;
  interval: readonly [number, number] | null;
  incomplete: boolean;
  cumulativeIncomplete: boolean;
}

export interface OrderBookRows {
  asks: readonly DisplayOrderBookLevel[];
  bids: readonly DisplayOrderBookLevel[];
  maxCumulative: number;
}

function cumulative(levels: readonly OrderBookLevel[], side: "bids" | "asks", step: number | null, incomplete: readonly number[], boundary?: number | null): DisplayOrderBookLevel[] {
  let total = 0;
  let cumulativeIncomplete = false;
  return levels.map(([price, quantity], slot) => {
    total += quantity;
    const partial = incomplete.includes(price);
    const beyondCoverage = boundary !== undefined && (boundary === null || (side === "bids" ? price <= boundary : price >= boundary));
    cumulativeIncomplete ||= partial || beyondCoverage;
    const interval: readonly [number, number] | null = step
      ? side === "bids" ? [price, price + step] : [Math.max(0, price - step), price]
      : null;
    return { slot, price, quantity, cumulative: total, interval, incomplete: partial, cumulativeIncomplete };
  });
}

export function buildOrderBookRows(
  bids: readonly OrderBookLevel[],
  asks: readonly OrderBookLevel[],
  step: number | null = null,
  incompleteBids: readonly number[] = [],
  incompleteAsks: readonly number[] = [],
  coverage?: { bidMin: number | null; askMax: number | null },
): OrderBookRows {
  const bidRows = cumulative(bids, "bids", step, incompleteBids, coverage?.bidMin);
  const askRows = cumulative(asks, "asks", step, incompleteAsks, coverage?.askMax);
  const maxCumulative = Math.max(
    0,
    bidRows[bidRows.length - 1]?.cumulative ?? 0,
    askRows[askRows.length - 1]?.cumulative ?? 0,
  );
  return Object.freeze({
    asks: Object.freeze(askRows),
    bids: Object.freeze(bidRows),
    maxCumulative,
  });
}
