import type { ExternalPriceLine } from "../../chart-adapter/externalPriceLineSource.js";
import { floorTo } from "./quickReplayModel.js";
import type { AccountSummary, PracticeOrder, Trade, TradeLeg } from "./tradingTypes.js";

/** Live chart overlay for the selected account: fills on this symbol, open position lines. */

export interface ChartInstrument {
  exchange: string;
  marketType: string;
  symbol: string;
}

export function sameInstrument(left: ChartInstrument, right: ChartInstrument): boolean {
  return left.exchange.trim().toLowerCase() === right.exchange.trim().toLowerCase()
    && left.marketType.trim().toLowerCase() === right.marketType.trim().toLowerCase()
    && left.symbol.trim().toUpperCase() === right.symbol.trim().toUpperCase();
}

/** Exact sum of two decimal strings, so merged legs never show 0.030000000000000002. */
export function addDecimalStrings(left: string, right: string): string {
  const scale = Math.max(left.split(".")[1]?.length ?? 0, right.split(".")[1]?.length ?? 0);
  const toUnits = (value: string) => {
    const negative = value.trim().startsWith("-");
    const [whole = "0", fraction = ""] = value.trim().replace(/^[-+]/, "").split(".");
    const units = BigInt(`${whole || "0"}${fraction.padEnd(scale, "0")}`);
    return negative ? -units : units;
  };
  const total = toUnits(left) + toUnits(right);
  const negative = total < 0n;
  const digits = (negative ? -total : total).toString().padStart(scale + 1, "0");
  const whole = digits.slice(0, digits.length - scale);
  const fraction = scale > 0 ? digits.slice(digits.length - scale).replace(/0+$/, "") : "";
  return `${negative ? "-" : ""}${whole}${fraction ? `.${fraction}` : ""}`;
}

export const MAX_LIVE_FILL_MARKERS = 200;

/**
 * Fills of the instrument's trades whose candle lies inside the loaded bars.
 * Fills outside that range are dropped because the chart would pin them to
 * the first or last bar. A reversal fill appears in two trades (close and
 * open); it is drawn once with its full quantity.
 */
export function liveFillLegs(
  trades: readonly Trade[],
  instrument: ChartInstrument,
  loaded: { firstSec: number; lastSec: number } | null,
  intervalSec: number,
  limit = MAX_LIVE_FILL_MARKERS,
): TradeLeg[] {
  if (loaded === null || !(intervalSec > 0)) return [];
  const byFill = new Map<string, TradeLeg>();
  for (const trade of trades) {
    if (!sameInstrument(trade, instrument)) continue;
    for (const leg of trade.legs) {
      const barSec = floorTo(Math.floor(leg.tsMs / 1000), intervalSec);
      if (barSec < loaded.firstSec || barSec > loaded.lastSec) continue;
      const seen = byFill.get(leg.fillId);
      byFill.set(leg.fillId, seen ? { ...seen, qty: addDecimalStrings(seen.qty, leg.qty) } : leg);
    }
  }
  return [...byFill.values()]
    .sort((left, right) => left.tsMs - right.tsMs)
    .slice(-limit);
}

export type PositionLineKind = "long" | "short" | "stopLoss" | "takeProfit";

export interface PositionLineColors {
  entry: string;
  stopLoss: string;
  takeProfit: string;
}

function exitKind(order: PracticeOrder): "stopLoss" | "takeProfit" | null {
  if (order.tag === "stop_loss") return "stopLoss";
  if (order.tag === "take_profit") return "takeProfit";
  if (!order.reduceOnly) return null;
  if (order.type === "stop") return "stopLoss";
  if (order.type === "limit") return "takeProfit";
  return null;
}

/** Average entry of each open position plus its working reduce-only exits. */
export function positionPriceLines(
  summary: Pick<AccountSummary, "positions" | "workingOrders"> | null,
  instrument: ChartInstrument,
  colors: PositionLineColors,
  label: (kind: PositionLineKind, qty: string) => string,
): ExternalPriceLine[] {
  if (summary === null) return [];
  const lines: ExternalPriceLine[] = [];
  for (const position of summary.positions) {
    if (position.status !== "open" || !sameInstrument(position, instrument)) continue;
    const price = Number(position.avgEntryPrice);
    if (!Number.isFinite(price) || price <= 0) continue;
    lines.push({
      id: `trading:entry:${position.id}`,
      price,
      color: colors.entry,
      title: label(position.direction, position.openQty),
      style: "solid",
      width: 2,
    });
  }
  for (const order of summary.workingOrders) {
    if (order.status !== "working" || !sameInstrument(order, instrument)) continue;
    const kind = exitKind(order);
    if (kind === null) continue;
    const price = Number(kind === "stopLoss" ? order.stopPrice : order.limitPrice);
    if (!Number.isFinite(price) || price <= 0) continue;
    lines.push({
      id: `trading:order:${order.id}`,
      price,
      color: kind === "stopLoss" ? colors.stopLoss : colors.takeProfit,
      title: label(kind, order.qty),
      style: "dashed",
      width: 1,
    });
  }
  return lines;
}
