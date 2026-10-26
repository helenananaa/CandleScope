import assert from "node:assert/strict";
import test from "node:test";
import {
  initialCursor,
  nextEventCursor,
  notesBefore,
  positionAt,
  replayEvents,
  visibleBars,
  type ReplayBar,
} from "./quickReplayModel.js";
import type { Trade, TradeLeg } from "./tradingTypes.js";

const HOUR = 3_600;

function bar(time: number, open: number, high: number, low: number, close: number): ReplayBar {
  return { time, open, high, low, close, volume: 1 };
}

function leg(fillId: string, side: "buy" | "sell", role: TradeLeg["role"], qty: string, price: string, tsMs: number): TradeLeg {
  return { fillId, side, role, qty, price, fee: "0", tsMs, liquidity: "taker", orderId: null };
}

const hourly = [bar(0, 100, 101, 99, 100), bar(HOUR, 100, 110, 95, 105), bar(2 * HOUR, 105, 120, 104, 118)];
const fiveMinute = Array.from({ length: 12 }, (_, index) => bar(HOUR + index * 300, 100 + index, 101 + index, 99 + index, 100.5 + index));

test("candles that are not complete at the cursor never reach the chart", () => {
  const shown = visibleBars(hourly, null, 2 * HOUR, HOUR, HOUR);
  assert.deepEqual(shown.map((item) => item.time), [0, HOUR]);
  // The 2h candle's high of 120 is in the future and must not leak.
  assert.ok(shown.every((item) => item.high < 120));
});

test("finer steps rebuild the forming candle only from closed finer candles", () => {
  const cursor = HOUR + 25 * 60; // 01:25
  const shown = visibleBars(hourly, fiveMinute, cursor, HOUR, 300);
  const partial = shown.at(-1)!;
  assert.equal(partial.time, HOUR);
  assert.equal(partial.open, 100);
  assert.equal(partial.high, 105); // five 5m candles: 01:00..01:20
  assert.equal(partial.close, 104.5);
  assert.notEqual(partial.high, 110); // the full 1h high happens later
});

test("position, P&L and excursions are computed as of the cursor", () => {
  const trade: Pick<Trade, "direction" | "legs"> = {
    direction: "long",
    legs: [
      leg("f1", "buy", "open", "2", "100", HOUR * 1000 + 600_000),
      leg("f2", "sell", "close", "2", "118", 2 * HOUR * 1000 + 1_800_000),
    ],
  };
  const atEntry = positionAt(trade, visibleBars(hourly, null, 2 * HOUR, HOUR, HOUR), 2 * HOUR, HOUR);
  assert.equal(atEntry.qty, 2);
  assert.equal(atEntry.avgEntry, 100);
  assert.equal(atEntry.unrealized, 10);
  assert.equal(atEntry.realized, 0);
  assert.equal(atEntry.mfe, 10);
  assert.equal(atEntry.mae, 5);
  const afterExit = positionAt(trade, visibleBars(hourly, null, 3 * HOUR, HOUR, HOUR), 3 * HOUR, HOUR);
  assert.equal(afterExit.qty, 0);
  assert.equal(afterExit.realized, 36);
});

test("events and notes are revealed by the cursor in order", () => {
  const trade = {
    legs: [leg("f1", "buy", "open", "1", "100", HOUR * 1000 + 600_000)],
    openedAtMs: HOUR * 1000 + 600_000,
  } as Trade;
  const note = { id: "n1", createdAtMs: 2 * HOUR * 1000 + 60_000, marketTimeMs: null } as never;
  const events = replayEvents(trade, [note]);
  assert.equal(initialCursor(trade, HOUR), HOUR);
  assert.equal(nextEventCursor(events, HOUR, HOUR), 2 * HOUR);
  assert.equal(nextEventCursor(events, 2 * HOUR, HOUR), 3 * HOUR);
  assert.deepEqual(notesBefore([note], 2 * HOUR), []);
  assert.equal(notesBefore([note], 3 * HOUR).length, 1);
});
