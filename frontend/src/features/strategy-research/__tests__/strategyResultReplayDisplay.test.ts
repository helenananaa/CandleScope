import assert from "node:assert/strict";
import test from "node:test";

import type { BacktestResultReplayBar, BacktestResultReplayFrame } from "../../backtest/backtestTypes.js";
import { changeReplayChartDisplay, DEFAULT_REPLAY_DISPLAY, replayChartMarkers } from "../strategyResultReplayDisplay.js";

test("only the edited setting follows its opt-in link", () => {
  const initial = changeReplayChartDisplay(DEFAULT_REPLAY_DISPLAY, "primary", "upColor", "#123456");
  assert.equal(initial.comparison.upColor, DEFAULT_REPLAY_DISPLAY.comparison.upColor);
  const linked = { ...initial, links: { ...initial.links, chartStyle: true, notes: true } };
  const styled = changeReplayChartDisplay(linked, "comparison", "candleStyle", "hollow");
  assert.equal(styled.primary.candleStyle, "hollow");
  assert.equal(styled.primary.upColor, "#123456");
  assert.equal(styled.comparison.upColor, DEFAULT_REPLAY_DISPLAY.comparison.upColor);
  const hiddenFills = changeReplayChartDisplay(styled, "primary", "fills", false);
  assert.equal(hiddenFills.comparison.fills, true);
  const hiddenNotes = changeReplayChartDisplay(hiddenFills, "comparison", "notes", false);
  assert.equal(hiddenNotes.primary.notes, false);
  assert.equal(hiddenNotes.comparison.notes, false);
});

test("markers require an owned chart, a revealed cursor and a matching candle", () => {
  const bars: BacktestResultReplayBar[] = [0, 100, 300].map(open_time_ms => ({
    open_time_ms, close_time_ms: open_time_ms + 99, closed: true,
    open: "1", high: "2", low: "1", close: "2", volume: "1",
  }));
  const fill = { cursor: 1, event_time_ms: 99, order_id: "first", side: "BUY", price: "1", qty: "1", fee: "0" };
  const note = { id: "note", revision: 1, cursor: 2, time_ms: 199, saved_at_ms: 999, body: "Seen" };
  const frame = {
    schema: "candlescope.local-bar-result-replay/1", run_id: "bt_example", snapshot_hash: "snapshot", report_hash: "report",
    symbol: "BTCUSDT", quote_asset: "USDT", interval: "1m", signal_interval: "1m",
    cursor: 3, total: 6, time_ms: 350, source_sequence: 3, bars,
    fills: [fill, { ...fill, cursor: 4, event_time_ms: 199 }, { ...fill, cursor: 3, event_time_ms: 399 },
      { ...fill, cursor: 3, event_time_ms: 250 }],
    notes: [note, { ...note, id: "initial", cursor: 0, time_ms: null },
      { ...note, id: "future", cursor: 4, time_ms: 199 }],
    fill_count: 1, order_events: [], order_trace_available: false, closed_bar_signals: [],
    signal_trace_available: false, cash: "1", position: "0", equity: "1",
  } satisfies BacktestResultReplayFrame;
  assert.deepEqual([...replayChartMarkers(frame, bars, true, DEFAULT_REPLAY_DISPLAY.primary)], [
    [0, { fills: [fill], notes: [] }], [1, { fills: [], notes: [note] }],
  ]);
  assert.equal(replayChartMarkers(frame, bars, false, DEFAULT_REPLAY_DISPLAY.comparison).size, 0);
  const rewind = { ...frame, cursor: 1, time_ms: 99 };
  assert.deepEqual([...replayChartMarkers(rewind, bars, true, DEFAULT_REPLAY_DISPLAY.primary)], [
    [0, { fills: [fill], notes: [] }],
  ]);
  assert.equal(replayChartMarkers(rewind, bars, true, { fills: false, notes: true }).size, 0);
});
