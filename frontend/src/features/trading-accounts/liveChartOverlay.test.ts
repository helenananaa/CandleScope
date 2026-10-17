import assert from "node:assert/strict";
import test from "node:test";
import {
  addDecimalStrings,
  liveFillLegs,
  positionPriceLines,
  sameInstrument,
} from "./liveChartOverlay.js";
import { fillMarkerGroups } from "./replayMarkerSource.js";
import type { PracticeOrder, Trade, TradeLeg } from "./tradingTypes.js";

const BTC = { exchange: "binance", marketType: "futures", symbol: "BTCUSDT" };
const HOUR = 3_600;

function leg(fillId: string, side: "buy" | "sell", role: TradeLeg["role"], qty: string, price: string, tsSec: number): TradeLeg {
  return { fillId, side, role, qty, price, fee: "0", tsMs: tsSec * 1000, liquidity: "taker", orderId: null };
}

function trade(id: string, legs: TradeLeg[], extra: Partial<Trade> = {}): Trade {
  return {
    id,
    accountId: "acc",
    ...BTC,
    direction: "long",
    status: "closed",
    openedAtMs: legs[0]!.tsMs,
    closedAtMs: null,
    openQty: "0",
    maxQty: "0",
    entryQty: "0",
    exitQty: "0",
    avgEntryPrice: null,
    avgExitPrice: null,
    realizedPnl: "0",
    fees: "0",
    netPnl: "0",
    markPrice: null,
    unrealizedPnl: null,
    legs,
    ...extra,
  };
}

function order(id: string, extra: Partial<PracticeOrder>): PracticeOrder {
  return {
    id,
    accountId: "acc",
    ...BTC,
    side: "sell",
    type: "stop",
    qty: "0.01",
    limitPrice: null,
    stopPrice: null,
    reduceOnly: true,
    tag: null,
    bracketStop: null,
    bracketTarget: null,
    status: "working",
    createdAtMs: 0,
    fillPrice: null,
    filledAtMs: null,
    reason: null,
    ...extra,
  };
}

test("instrument match ignores case and padding", () => {
  assert.equal(sameInstrument({ exchange: " Binance", marketType: "FUTURES", symbol: "btcusdt" }, BTC), true);
  assert.equal(sameInstrument({ ...BTC, marketType: "spot" }, BTC), false);
  assert.equal(sameInstrument({ ...BTC, symbol: "ETHUSDT" }, BTC), false);
});

test("decimal strings add exactly", () => {
  assert.equal(addDecimalStrings("0.01", "0.02"), "0.03");
  assert.equal(addDecimalStrings("1", "0.5"), "1.5");
  assert.equal(addDecimalStrings("0.25", "0.75"), "1");
  assert.equal(addDecimalStrings("-0.1", "0.3"), "0.2");
  assert.equal(addDecimalStrings("0.1", "-0.3"), "-0.2");
});

test("fill legs keep this instrument inside the loaded bars only", () => {
  const base = 1_700_000_000 - (1_700_000_000 % HOUR);
  const trades = [
    trade("t1", [leg("f1", "buy", "open", "0.01", "100", base - 2 * HOUR), leg("f2", "sell", "close", "0.01", "110", base + 30)]),
    trade("t2", [leg("f3", "buy", "open", "1", "5", base + 60)], { symbol: "ETHUSDT" }),
    trade("t3", [leg("f4", "buy", "open", "0.02", "120", base + HOUR + 10)]),
  ];
  const legs = liveFillLegs(trades, BTC, { firstSec: base, lastSec: base }, HOUR);
  assert.deepEqual(legs.map((item) => item.fillId), ["f2"]);
  assert.deepEqual(liveFillLegs(trades, BTC, null, HOUR), []);
  // the last bar's candle includes fills from anywhere inside it
  assert.deepEqual(
    liveFillLegs(trades, BTC, { firstSec: base, lastSec: base + HOUR }, HOUR).map((item) => item.fillId),
    ["f2", "f4"],
  );
});

test("a reversal fill is drawn once with its full quantity", () => {
  const base = 1_700_000_000 - (1_700_000_000 % HOUR);
  const trades = [
    trade("t1", [leg("f1", "buy", "open", "0.01", "100", base), leg("f2", "sell", "close", "0.01", "110", base + 60)]),
    trade("t1~r", [leg("f2", "sell", "open", "0.02", "110", base + 60)], { direction: "short" }),
  ];
  const legs = liveFillLegs(trades, BTC, { firstSec: base, lastSec: base }, HOUR);
  assert.equal(legs.length, 2);
  assert.equal(legs[1]!.fillId, "f2");
  assert.equal(legs[1]!.qty, "0.03");
});

test("fill legs are capped to the most recent", () => {
  const base = 1_700_000_000 - (1_700_000_000 % 60);
  const legs = Array.from({ length: 5 }, (_, index) => leg(`f${index}`, "buy", "add", "1", "1", base + index * 60));
  const kept = liveFillLegs([trade("t", legs)], BTC, { firstSec: base, lastSec: base + 600 }, 60, 3);
  assert.deepEqual(kept.map((item) => item.fillId), ["f2", "f3", "f4"]);
});

test("position lines: entry plus reduce-only exits on this instrument", () => {
  const colors = { entry: "blue", stopLoss: "red", takeProfit: "green" };
  const label = (kind: string, qty: string) => `${kind} ${qty}`;
  const position = trade("t1", [leg("f1", "buy", "open", "0.01", "100", 0)], {
    status: "open",
    openQty: "0.01",
    avgEntryPrice: "100.5",
  });
  const lines = positionPriceLines({
    positions: [position, { ...position, id: "t2", symbol: "ETHUSDT" }],
    workingOrders: [
      order("sl", { tag: "stop_loss", stopPrice: "95" }),
      order("tp", { tag: "take_profit", type: "limit", limitPrice: "120" }),
      order("manual-stop", { stopPrice: "90" }),
      order("entry", { reduceOnly: false, side: "buy", type: "limit", limitPrice: "98" }),
      order("eth", { symbol: "ETHUSDT", stopPrice: "1" }),
      order("gone", { status: "cancelled", stopPrice: "94" }),
    ],
  }, BTC, colors, label);
  assert.deepEqual(lines.map((line) => [line.id, line.price, line.color, line.title, line.style]), [
    ["trading:entry:t1", 100.5, "blue", "long 0.01", "solid"],
    ["trading:order:sl", 95, "red", "stopLoss 0.01", "dashed"],
    ["trading:order:tp", 120, "green", "takeProfit 0.01", "dashed"],
    ["trading:order:manual-stop", 90, "red", "stopLoss 0.01", "dashed"],
  ]);
  assert.deepEqual(positionPriceLines(null, BTC, colors, label), []);
});

test("same-side fills in one candle share a marker with exact qty and weighted price", () => {
  const groups = fillMarkerGroups([
    leg("f1", "buy", "open", "0.001", "82000.5", 10 * HOUR + 60),
    leg("f2", "buy", "open", "0.002", "82003", 10 * HOUR + 600),
    leg("f3", "sell", "close", "0.001", "82100", 10 * HOUR + 900),
    leg("f4", "buy", "open", "0.1", "81000", 11 * HOUR),
  ], HOUR);
  assert.deepEqual(groups, [
    { time: 10 * HOUR, side: "buy", qty: "0.003", price: 82002.2, count: 2 },
    { time: 10 * HOUR, side: "sell", qty: "0.001", price: 82100, count: 1 },
    { time: 11 * HOUR, side: "buy", qty: "0.1", price: 81000, count: 1 },
  ]);
});
