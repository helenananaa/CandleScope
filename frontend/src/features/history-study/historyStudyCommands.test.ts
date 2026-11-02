import assert from "node:assert/strict";
import test from "node:test";
import { AppCommandRegistry } from "../app-control/commandRegistry.js";
import type { ChartSurfaceRuntime } from "../../chart-adapter/useChartSurfaceRuntime.js";
import type { IndicatorRuntime } from "../indicators/indicatorRuntimeContract.js";
import { historyStudyCommands } from "./historyStudyCommands.js";
import { HistoryStudyDataManager } from "./historyStudyDataManager.js";
import { HistoryStudyPlayback } from "./historyStudyPlayback.js";

function fixture() {
  const playback = new HistoryStudyPlayback({ id: "study-a", capturedAtMs: 5_000_000,
    inputKind: "captured-market-history", series: { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "5m" },
    rows: Array.from({ length: 4 }, (_, i) => ({ time: (i + 1) * 300, closeTimeMs: (i + 2) * 300_000,
      open: 10, high: 20, low: 5, close: 15, volume: 1, is_closed: true })) }, 900_000);
  const viewport: unknown[] = [], moves: unknown[] = [];
  const abort = new AbortController();
  const input: Parameters<typeof historyStudyCommands>[0] = {
    cellId: "a", playback, revision: 1, busy: false, playing: false, renderedVersion: Number(playback.store.version),
    indicators: { status: { computing: false }, view: { activeIndicators: [{ id: "ma", lines: [{
      data: [300, 600, 900, 1200].map(time => ({ time, value: 15 })),
    }] }] } } as IndicatorRuntime,
    surface: { actions: { getVisibleRange: () => null,
      setLinkedVisibleTimeRange: (value: unknown) => { viewport.push(value); return true; },
      centerVisibleTime: (value: unknown) => { viewport.push(value); return true; },
      setLinkedCrosshairTime: (value: unknown) => { viewport.push(value); return true; },
    } } as unknown as ChartSurfaceRuntime,
    data: new HistoryStudyDataManager(async () => ({ notes: [] })),
    move: async (cursor, active) => { moves.push({ cursor, active }); playback.seek(cursor); return true; },
    play: value => { input.playing = value; }, signal: () => abort.signal,
  };
  const registry = new AppCommandRegistry();
  const release = registry.register(historyStudyCommands(input));
  const query = (command: string, args = {}) => registry.execute({ id: "query", method: "app.query",
    params: { windowId: "w", groupId: "study:a", command, args } }, "w");
  const execute = (command: string, args = {}, token = registry.list()[0]!.contextToken) => registry.execute({ id: "write", method: "app.execute",
    params: { windowId: "w", groupId: "study:a", command, args, requestId: "write", expectedContext: token } }, "w");
  return { input, playback, registry, query, execute, viewport, moves, abort, release };
}

test("control reads expose only revealed input and bounded indicator outputs", async () => {
  const f = fixture();
  const bars = await f.query("bars", { limit: 1 });
  assert.deepEqual((bars.output as { time: number }[]).map(row => row.time), [600]);
  const outputs = await f.query("indicatorOutputs", { limit: 500 });
  assert.deepEqual((outputs.output as { lines: { data: { time: number }[] }[] }[])[0]!.lines[0]!.data.map(p => p.time), [300, 600]);
  const snapshot = (await f.query("inspect")).snapshot as Record<string, unknown>;
  assert.equal(snapshot.barCount, 2);
  assert.equal(snapshot.lastTime, 600);
  assert.equal((snapshot.indicators as { outputPoints: number }[])[0]!.outputPoints, 2);
  assert.equal("rows" in snapshot, false);
  assert.equal((await f.query("bars", { limit: 501 })).state, "failed");
  f.playback.seek(600_000); // Store changes before React publishes new commands.
  assert.equal((await f.query("indicatorOutputs", { limit: 500 })).message, "COMMAND_DISABLED");
});

test("viewport actions never advance time or navigate into retained future bars", async () => {
  const f = fixture();
  assert.equal((await f.execute("visibleTimeRange", { from: 300, to: 600 })).state, "applied");
  assert.equal((await f.execute("timeAnchor", { time: 300 })).state, "applied");
  assert.equal((await f.execute("crosshair", { time: null })).state, "applied");
  assert.equal((await f.execute("visibleTimeRange", { from: 300, to: 900 })).state, "failed");
  assert.equal(f.playback.cursorMs, 900_000);
  assert.deepEqual(f.moves, []);
  assert.equal(f.viewport.length, 3);
});

test("cursor actions use durable movement, reject out-of-range input and invalidate old contexts", async () => {
  const f = fixture(), token = f.registry.list()[0]!.contextToken;
  assert.equal((await f.execute("seekCursor", { timeMs: 1 }, token)).state, "failed");
  assert.deepEqual(f.moves, []);
  assert.equal((await f.execute("step", { direction: "backward" }, token)).state, "applied");
  assert.deepEqual(f.moves, [{ cursor: 600_000, active: true }]);
  assert.equal((await f.execute("play", {}, token)).message, "CONTEXT_CONFLICT");
  f.input.busy = true;
  assert.equal((await f.execute("exit")).message, "COMMAND_DISABLED");
  f.input.busy = false;
  assert.equal((await f.execute("exit")).state, "applied");
  assert.deepEqual(f.moves.at(-1), { cursor: 600_000, active: false });
});

test("late notes are rejected after rewind, including an intrabar rewind without a bar-store revision", async () => {
  const f = fixture();
  f.playback.seek(950_000);
  let resolve!: (value: unknown) => void;
  f.input.data = new HistoryStudyDataManager(() => new Promise(done => { resolve = done; }));
  const pending = f.query("notes");
  f.playback.seek(925_000);
  resolve({ notes: [{ marketTimeMs: 900_000, fields: { entryBasis: "future" } }] });
  const result = await pending;
  assert.equal(result.state, "failed");
  assert.equal(result.message, "STUDY_CONTEXT_CHANGED");
  assert.equal("output" in result, false);
});

test("study teardown aborts an in-flight note reader and removes its commands", async () => {
  const f = fixture();
  let resolve!: (value: unknown) => void;
  f.input.data = new HistoryStudyDataManager(() => new Promise(done => { resolve = done; }));
  const pending = f.query("notes");
  f.abort.abort(); f.release(); resolve({ notes: [] });
  assert.equal((await pending).state, "failed");
  assert.equal((await f.query("bars", { limit: 1 })).message, "GROUP_UNAVAILABLE");
  assert.equal(f.input.data.diagnostics().requests, 0);
});

test("source notes cannot retain the previous cursor's text across an intrabar rewind", async () => {
  const f = fixture();
  f.playback.seek(950_000);
  const version = Number(f.playback.store.version);
  f.input.journal = { enabled: true, accountId: "a", accountName: "Source", cursorMs: 950_000, hasMore: false,
    loading: false, error: null, original: [{ id: "note", accountId: "a", marketTimeMs: 940_000,
      createdAtMs: 940_000, savedAtMs: 940_000, revision: 1, fields: {}, body: "later text", reviewNote: false, historyUnavailable: false }], reviews: [] };
  assert.equal((await f.query("originalNotes", { limit: 1 })).state, "ready");
  f.playback.seek(925_000);
  assert.equal(Number(f.playback.store.version), version);
  assert.equal((await f.query("originalNotes", { limit: 1 })).message, "COMMAND_DISABLED");
  f.input.journal = { ...f.input.journal, cursorMs: 925_000, original: [] };
  const result = await f.query("originalNotes", { limit: 1 });
  assert.deepEqual((result.output as { notes: unknown[] }).notes, []);
});
