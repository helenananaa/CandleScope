import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import type { BacktestResultReplayBar, BacktestResultReplayFrame } from "../../backtest/backtestTypes.js";
import { changeReplayChartDisplay, DEFAULT_REPLAY_DISPLAY, readReplayDisplays, replayChartDisplay, replayChartMarkers, replayLayout, restoreReplayLayout } from "../strategyResultReplayDisplay.js";
import { StrategyResultReplayChart } from "../StrategyResultReplayChart.js";
import { editReplayDrawings, replayDrawingBarIndex, replayDrawingOwner, replayDrawingScope, revealedReplayDrawings, type ReplayDrawing } from "../strategyResultReplayDrawings.js";

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

test("the moving average visibility link affects visible slots and survives reload", () => {
  const key = `bt_first:sha256:${"1".repeat(64)}:sha256:${"2".repeat(64)}`;
  const legacy = readReplayDisplays({ [key]: { primary: { candleStyle: "hollow" }, links: { chartStyle: true } } })![key]!;
  assert.equal(legacy.primary.showMa, true);
  assert.equal(legacy.links.indicatorVisibility, false);
  const local = changeReplayChartDisplay(legacy, "primary", "showMa", false);
  assert.equal(local.comparison.showMa, true);
  const linked = changeReplayChartDisplay({ ...local, links: { ...local.links, indicatorVisibility: true } },
    "comparison", "showMa", false, ["primary", "comparison", "extra1"]);
  const restored = readReplayDisplays(JSON.parse(JSON.stringify({ [key]: linked })))![key]!;
  assert.equal(restored.links.indicatorVisibility, true);
  const slots = ["primary", "comparison", "extra1", "extra2"] as const;
  assert.deepEqual(slots.map(slot => replayChartDisplay(restored, slot).showMa), [false, false, false, true]);
  assert.equal(restored.primary.candleStyle, "hollow");
  assert.equal(restored.comparison.fills, true);
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

  const chart = { ...frame, ma: { period: 2, points: [{ open_time_ms: 100, value: 1.5 }] } };
  const render = (showMa: boolean) => renderToStaticMarkup(createElement(StrategyResultReplayChart, {
    slot: "primary", chart, frame, display: { ...DEFAULT_REPLAY_DISPLAY.primary, showMa }, disabled: false, onChange() {},
  }));
  assert.match(render(true), /data-testid="strategy-replay-ma-line"/);
  assert.match(render(true), /data-testid="strategy-replay-ma"/);
  const hidden = render(false);
  assert.doesNotMatch(hidden, /data-testid="strategy-replay-ma(?:-line)?"/);
  assert.match(hidden, /data-testid="strategy-replay-fill-marker"/);
  assert.match(hidden, /data-testid="strategy-replay-last-ohlc"/);

  const drawing: ReplayDrawing = {
    id: "6c62a01d-c890-43f1-8845-d77bc99cc384", cursor: 4, points: [{ timeMs: 100, price: 1.5 }],
  };
  const renderDrawings = (cursor: number, showDrawings = true) => renderToStaticMarkup(createElement(StrategyResultReplayChart, {
    slot: "primary", chart, frame: { ...frame, cursor }, display: { ...DEFAULT_REPLAY_DISPLAY.primary, showDrawings },
    disabled: false, drawingControl: { owner: "run", drawings: [drawing], locked: false, edit: () => true }, onChange() {},
  }));
  assert.match(renderDrawings(4), /data-testid="strategy-replay-drawing"/);
  assert.doesNotMatch(renderDrawings(3), /data-testid="strategy-replay-drawing"/);
  assert.doesNotMatch(renderDrawings(4, false), /data-testid="strategy-replay-drawing"/);
  assert.equal(replayDrawingBarIndex(bars, 199), 1);
  assert.equal(replayDrawingBarIndex(bars, 200), -1);
});

test("result drawings round-trip with per-slot and per-dataset ownership", () => {
  const key = `bt_drawings:sha256:${"1".repeat(64)}:sha256:${"2".repeat(64)}`;
  const drawing: ReplayDrawing = { id: "6c62a01d-c890-43f1-8845-d77bc99cc384", cursor: 3,
    points: [{ timeMs: 200, price: 10 }, { timeMs: 300, price: 12 }] };
  const reference = replayDrawingOwner({ dataset_id: `local-${"a".repeat(32)}`, data_epoch: `sha256:${"2".repeat(64)}` });
  assert.ok(reference);
  assert.equal(replayDrawingOwner({ dataset_id: `local-${"a".repeat(32)}` }), null);
  const primary = replayDrawingScope("primary", "run");
  const comparison = replayDrawingScope("comparison", "run");
  const pinned = replayDrawingScope("comparison", reference);
  const documents = editReplayDrawings({}, [primary, comparison], { add: drawing })!;
  const pinnedDocuments = editReplayDrawings(documents, [pinned], { add: { ...drawing, cursor: 7 } })!;
  const removed = editReplayDrawings(pinnedDocuments, [primary, comparison], { remove: drawing.id });
  assert.deepEqual(removed, { [pinned]: [{ ...drawing, cursor: 7 }] });
  const display = { ...DEFAULT_REPLAY_DISPLAY, drawings: pinnedDocuments };
  const restored = readReplayDisplays(JSON.parse(JSON.stringify({ [key]: display })))![key]!;
  assert.deepEqual(restored.drawings, pinnedDocuments);
  assert.deepEqual(revealedReplayDrawings(restored.drawings![pinned]!, 6, 300), []);
  assert.deepEqual(revealedReplayDrawings(restored.drawings![pinned]!, 7, 299), []);
});

test("saved references and styles are isolated by result and links touch only visible slots", () => {
  const key = `bt_first:sha256:${"1".repeat(64)}:sha256:${"2".repeat(64)}`;
  const other = `bt_other:sha256:${"3".repeat(64)}:sha256:${"4".repeat(64)}`;
  const references = {
    extra1: { interval: "15m", maPeriod: 8 },
    extra2: { interval: "1m", dataset: { datasetId: `local-${"a".repeat(32)}`, dataEpoch: `sha256:${"a".repeat(64)}` } },
  };
  const raw = { ...DEFAULT_REPLAY_DISPLAY, links: { ...DEFAULT_REPLAY_DISPLAY.links, chartStyle: true }, references };
  const linked = changeReplayChartDisplay(raw, "extra1", "candleStyle", "hollow", ["primary", "extra1", "extra2"]);
  assert.equal(replayChartDisplay(linked, "extra2").candleStyle, "hollow");
  assert.equal(linked.comparison.candleStyle, "solid");
  assert.equal(linked.references, references);
  const restored = readReplayDisplays(JSON.parse(JSON.stringify({ [key]: linked, [other]: DEFAULT_REPLAY_DISPLAY })))!;
  assert.deepEqual(restored[key]!.references, references);
  assert.equal(replayChartDisplay(restored[key]!, "extra1").candleStyle, "hollow");
  assert.equal(restored[other]!.references, undefined);
  assert.equal(replayChartDisplay(restored[other]!, "extra1").candleStyle, "solid");
});

test("returning to a report and reopening restores all chart inputs for that result", () => {
  const initial = { runId: "bt_example", snapshotHash: `sha256:${"1".repeat(64)}`, reportHash: `sha256:${"2".repeat(64)}`,
    cursor: 0, interval: "1m" };
  const configured = { ...initial, interval: "5m", maPeriod: 8, comparisonInterval: "15m", comparisonMaPeriod: 12,
    additionalCharts: { extra1: { interval: "1h" } } };
  const display = { ...DEFAULT_REPLAY_DISPLAY, layout: replayLayout(configured), references: configured.additionalCharts };
  const key = `${initial.runId}:${initial.snapshotHash}:${initial.reportHash}`;
  const saved = readReplayDisplays(JSON.parse(JSON.stringify({ [key]: display })))![key]!;
  assert.deepEqual(restoreReplayLayout(initial, saved), configured);
  const inactive = restoreReplayLayout({ ...initial, comparisonInterval: "15m" },
    { ...DEFAULT_REPLAY_DISPLAY, layout: replayLayout(initial) });
  assert.deepEqual(inactive, initial);
});
