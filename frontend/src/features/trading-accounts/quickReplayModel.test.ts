import assert from "node:assert/strict";
import test from "node:test";
import {
  initialCursor,
  journalAtCursor,
  nextEventCursor,
  notesBefore,
  positionAt,
  replayEvents,
  visibleBars,
  type ReplayBar,
} from "./quickReplayModel.js";
import type { JournalEntry, Trade, TradeLeg } from "./tradingTypes.js";

const HOUR = 3_600;
const baseNote: JournalEntry = {
  id: "note", accountId: "account", exchange: "binance", marketType: "futures", symbol: "BTCUSDT",
  kind: "note", tradeId: "trade", createdAtMs: 0, updatedAtMs: 0, marketTimeMs: null,
  templateId: null, templateVersion: null, tags: [], fields: {}, body: "", revisionCount: 1,
  stage: "pre", reviewNote: false, fieldTiming: {}, plan: null, snapshots: [],
};

test("rewind selects saved content, clips snapshots and separates later review notes", () => {
  const note: JournalEntry = { ...baseNote,
    id: "note", createdAtMs: 9 * HOUR * 1000, updatedAtMs: 11 * HOUR * 1000,
    marketTimeMs: null, fields: { entryBasis: "future" }, body: "future",
    snapshots: [{ id: "before", createdAtMs: 9 * HOUR * 1000, hasImage: false, state: {} }, { id: "after", createdAtMs: 11 * HOUR * 1000, hasImage: false, state: {} }],
    plan: { lockedAtMs: 10 * HOUR * 1000, entryPrice: "100", stopPrice: "90", targetPrice: "110", riskUsdt: "10" },
    revisions: [
      { revision: 1, savedAtMs: 9 * HOUR * 1000, fields: { entryBasis: "original" }, body: "original", historyComplete: true },
      { revision: 2, savedAtMs: 11 * HOUR * 1000, fields: { entryBasis: "future" }, body: "future", historyComplete: true },
    ],
  };
  const review = { ...note, id: "review", createdAtMs: 20 * HOUR * 1000, marketTimeMs: 9 * HOUR * 1000 };
  for (const cursor of [10 * HOUR, 12 * HOUR, 10 * HOUR]) {
    const cut = journalAtCursor([note, review], cursor);
    assert.equal(cut.notes.length, 1);
    assert.equal(cut.notes[0]!.body, cursor === 12 * HOUR ? "future" : "original");
    assert.equal(cut.notes[0]!.snapshots.length, cursor === 12 * HOUR ? 2 : 1);
    assert.equal(cut.notes[0]!.plan === null, cursor === 10 * HOUR);
    assert.equal(cut.reviewNotes[0]!.id, "review");
  }
  assert.equal(journalAtCursor([note], 9 * HOUR).notes.length, 0);
  assert.equal(journalAtCursor([note], 11 * HOUR).notes[0]!.body, "original");
  assert.equal(note.body, "future"); // projection never mutates source
});

test("legacy or missing revision coverage never falls back to current text", () => {
  const note: JournalEntry = { ...baseNote, id: "old", createdAtMs: 1000, marketTimeMs: null, fields: { entryBasis: "future" },
    body: "future", snapshots: [], plan: null,
    revisions: [{ revision: 1, savedAtMs: 5000, body: "future", fields: {}, historyComplete: false }],
  };
  for (const cursor of [2, 6]) {
    const result = journalAtCursor([note], cursor).notes[0]!;
    assert.equal(result.historyUnavailable, true);
    assert.equal(result.body, "");
    assert.deepEqual(result.fields, {});
  }
  const missing = { ...note };
  delete missing.revisions;
  assert.equal(journalAtCursor([missing], 6).notes[0]!.body, "");
});

test("review save time is not moved by later trade-link metadata changes", () => {
  const review: JournalEntry = { ...baseNote, id: "review", kind: "quick",
    createdAtMs: 5000, updatedAtMs: 9000, marketTimeMs: 1000, body: "review text",
    revisions: [{ revision: 1, savedAtMs: 5000, fields: {}, body: "review text", historyComplete: true }],
  };
  const projected = journalAtCursor([review], 2).reviewNotes[0]!;
  assert.equal(projected.updatedAtMs, 5000);
  assert.equal(projected.body, "review text");
  assert.equal(review.updatedAtMs, 9000);
});

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
