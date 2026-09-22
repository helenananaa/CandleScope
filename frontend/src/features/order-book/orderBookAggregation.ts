import { partialStepScores } from "./orderBookAuto.js";
import type {
  OrderBookBook,
  OrderBookLevel,
  OrderBookMode,
  PriceGrouping,
} from "./orderBookTypes.js";

export interface OrderBookPresentation {
  bids: readonly OrderBookLevel[];
  asks: readonly OrderBookLevel[];
  priceStep: number | null;
  aggregationApplied: boolean;
  incompleteBidPrices: readonly number[];
  incompleteAskPrices: readonly number[];
  coverageBidMin: number | null;
  coverageAskMax: number | null;
}

export function resolvePriceStep(
  priceTickSize: number | null,
  grouping: PriceGrouping,
): number | null {
  if (!priceTickSize || !Number.isFinite(priceTickSize) || priceTickSize <= 0) return null;
  // Auto needs a real book and viewport; do not advertise a price-only estimate.
  if (grouping === "auto") return null;
  return grouping === "raw" ? priceTickSize : priceTickSize * Number(grouping);
}

export function aggregateOrderBookLevels(
  levels: readonly OrderBookLevel[],
  side: "bids" | "asks",
  priceStep: number,
): readonly OrderBookLevel[] {
  if (!Number.isFinite(priceStep) || priceStep <= 0 || levels.length === 0) return levels;
  const scale = decimalScale(priceStep, levels);
  const stepUnits = Math.round(priceStep * scale);
  if (!Number.isSafeInteger(stepUnits) || stepUnits <= 0) return levels;

  const buckets = new Map<number, number>();
  for (const [price, quantity] of levels) {
    const priceUnits = Math.round(price * scale);
    if (!Number.isSafeInteger(priceUnits)) return levels;
    const bucketUnits = (side === "bids" ? Math.floor : Math.ceil)(priceUnits / stepUnits)
      * stepUnits;
    buckets.set(bucketUnits, (buckets.get(bucketUnits) ?? 0) + quantity);
  }
  return Object.freeze([...buckets.entries()]
    .sort(([left], [right]) => side === "bids" ? right - left : left - right)
    .map(([priceUnits, quantity]) => (
      Object.freeze([priceUnits / scale, quantity] as const)
    )));
}

export function orderBookPresentation(
  book: OrderBookBook,
  grouping: PriceGrouping,
  rangeBps = 0,
): OrderBookPresentation {
  if (book.mode === "full") {
    return {
      bids: book.bids,
      asks: book.asks,
      priceStep: book.priceStep,
      aggregationApplied: book.aggregationApplied,
      incompleteBidPrices: book.incompleteBidPrices ?? (book.aggregationApplied ? book.bids.map(([price]) => price) : []),
      incompleteAskPrices: book.incompleteAskPrices ?? (book.aggregationApplied ? book.asks.map(([price]) => price) : []),
      coverageBidMin: book.coverageBidMin ?? null,
      coverageAskMax: book.coverageAskMax ?? null,
    };
  }
  const priceStep = grouping === "auto"
    ? (book.autoPriceStep ?? [...partialStepScores(book, 12, rangeBps)].sort(([a, sa], [b, sb]) => sa - sb || a - b)[0]?.[0] ?? book.priceTickSize)
    : resolvePriceStep(book.priceTickSize, grouping);
  const aggregationApplied = (
    priceStep !== null
    && book.priceTickSize !== null
    && priceStep > book.priceTickSize * (1 + Number.EPSILON)
  );
  const groupedBids = aggregationApplied
    ? aggregateOrderBookLevels(book.bids, "bids", priceStep)
    : book.bids;
  const groupedAsks = aggregationApplied
    ? aggregateOrderBookLevels(book.asks, "asks", priceStep)
    : book.asks;
  const clip = (levels: readonly OrderBookLevel[]) => {
    const near = levels[0]?.[0];
    return !rangeBps || !near ? levels : levels.filter(([price]) => Math.abs(price - near) <= near * rangeBps / 10_000);
  };
  const bids = clip(groupedBids);
  const asks = clip(groupedAsks);
  const coverageBidMin = book.bids.at(-1)?.[0] ?? null;
  const coverageAskMax = book.asks.at(-1)?.[0] ?? null;
  return {
    bids,
    asks,
    incompleteBidPrices: aggregationApplied ? bids.filter(([price]) => coverageBidMin === null || price <= coverageBidMin).map(([price]) => price) : [],
    incompleteAskPrices: aggregationApplied ? asks.filter(([price]) => coverageAskMax === null || price >= coverageAskMax).map(([price]) => price) : [],
    coverageBidMin,
    coverageAskMax,
    priceStep,
    aggregationApplied,
  };
}

export function groupingPriceStep(
  book: OrderBookBook | null,
  mode: OrderBookMode,
  grouping: PriceGrouping,
): number | null {
  if (!book) return null;
  if (mode === "partial" && grouping === "auto") return orderBookPresentation(book, grouping).priceStep;
  if (grouping === book.priceGrouping) return book.priceStep;
  return resolvePriceStep(book.priceTickSize, grouping);
}

function decimalScale(value: number, levels: readonly OrderBookLevel[]): number {
  const decimals = Math.max(
    decimalPlaces(value),
    ...levels.map(([price]) => decimalPlaces(price)),
  );
  return 10 ** Math.min(10, decimals);
}

function decimalPlaces(value: number): number {
  const text = value.toString().toLowerCase();
  const [coefficient = text, exponentText] = text.split("e");
  const exponent = exponentText === undefined ? 0 : Number(exponentText);
  const fractionLength = coefficient.split(".")[1]?.length ?? 0;
  return Math.max(0, fractionLength - exponent);
}
