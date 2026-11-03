import assert from "node:assert/strict";
import test from "node:test";
import type { ChartSurfaceActions } from "../../chart-adapter/useChartSurfaceRuntime.js";
import { HistoryStudyPlayback } from "./historyStudyPlayback.js";
import type { HistoryStudy } from "./historyStudyTypes.js";
import { locateStudyViewportTime } from "./historyStudyNavigation.js";
import { createStudyLinkSurface } from "./historyStudyLinkSurface.js";

function study(): HistoryStudy {
  return { id: "navigation", inputKind: "captured-market-history", capturedAtMs: 1_000_000,
    series: { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" },
    rows: Array.from({ length: 8 }, (_, i) => ({ time: i * 60, closeTimeMs: (i + 1) * 60_000,
      open: 1, high: 2, low: 0, close: 1, volume: 1, is_closed: true })) };
}
function locate(playback: HistoryStudyPlayback, time: number) {
  return locateStudyViewportTime({ store: playback.store, interval: playback.input.series.interval,
    minimumMs: playback.minimumMs, cursorMs: playback.cursorMs }, time);
}

test("date navigation only reads the revealed prefix and never advances or rewrites its clock", () => {
  const playback = new HistoryStudyPlayback(study(), 240_000);
  const rows = playback.store.snapshot(), version = Number(playback.store.version);
  assert.deepEqual(locate(playback, 60_123), { status: "located", requestedTimeMs: 60_123, actualTimeMs: 60_000, exact: true });
  assert.deepEqual(locate(playback, 240_000), { status: "located", requestedTimeMs: 240_000, actualTimeMs: 180_000, exact: false });
  assert.equal(locate(playback, 240_001).status, "unavailable");
  assert.equal(locate(playback, -1).status, "invalid");
  assert.equal(locate(playback, NaN).status, "invalid");
  assert.equal(playback.cursorMs, 240_000);
  assert.equal(Number(playback.store.version), version);
  assert.equal(playback.store.snapshot(), rows);
  const later = study(); later.rows = later.rows.slice(1);
  assert.equal(locate(new HistoryStudyPlayback(later, 240_000), 0).status, "unavailable");
});

test("gaps disclose the nearest revealed bar with an earlier tie, and an empty prefix stays empty", () => {
  const input = study(); input.rows = input.rows.filter(row => row.time !== 120);
  const playback = new HistoryStudyPlayback(input, 300_000);
  assert.deepEqual(locate(playback, 120_000), { status: "located", requestedTimeMs: 120_000, actualTimeMs: 60_000, exact: false });
  playback.seek(0);
  assert.equal(locate(playback, 0).status, "empty");
  assert.equal(locate(playback, 1).status, "unavailable");
});

test("calendar display navigation maps a leap-day request to the revealed month, not a fixed-width offset", () => {
  const start = Date.UTC(2024, 0, 1) / 1000, input = study();
  input.series.interval = "1M"; input.sourceSeries = { ...input.series, interval: "1d" };
  input.rows = Array.from({ length: 65 }, (_, i) => ({ time: start + i * 86400, closeTimeMs: (start + (i + 1) * 86400) * 1000,
    open: 1, high: 2, low: 0, close: 1, volume: 1, is_closed: true }));
  const playback = new HistoryStudyPlayback(input, Date.UTC(2024, 2, 2));
  const result = locate(playback, Date.UTC(2024, 1, 29, 12));
  assert.equal(result.status, "located");
  if (result.status === "located") assert.equal(result.actualTimeMs, Date.UTC(2024, 1, 1));
  assert.equal(playback.cursorMs, Date.UTC(2024, 2, 2));
});

test("linked viewport/crosshair operations target only the study, reject future time and wait for publication", () => {
  const playback = new HistoryStudyPlayback(study(), 180_000);
  let rendered = Number(playback.store.version);
  const calls: unknown[] = [];
  const actions = { setLinkedCrosshairTime: (value: unknown) => { calls.push(["crosshair", value]); return true; },
    setLinkedVisibleTimeAnchor: (value: unknown) => { calls.push(["anchor", value]); return true; },
    setLinkedVisibleTimeRange: (value: unknown) => { calls.push(["range", value]); return true; },
    subscribeLinkedViewportReady: () => () => {},
  } as unknown as ChartSurfaceActions;
  const surface = createStudyLinkSurface(playback, () => rendered, actions);
  assert.equal(surface.setLinkedCrosshairTime(121), true);
  assert.deepEqual(calls.at(-1), ["crosshair", 120]);
  assert.equal(surface.setLinkedCrosshairTime(181), false);
  assert.deepEqual(calls.at(-1), ["crosshair", null]);
  assert.equal(surface.setLinkedVisibleTimeRange({ from: 61.0001, to: 121.0001 }), true);
  assert.deepEqual(calls.at(-1), ["range", { from: 60, to: 120 }]);
  const count = calls.length;
  assert.equal(surface.setLinkedVisibleTimeAnchor(181), false);
  assert.equal(calls.length, count);
  assert.equal(playback.cursorMs, 180_000);
  assert.equal(Object.hasOwn(surface, "setLinkedDrawingRevision"), false);
  playback.seek(240_000);
  assert.equal(surface.setLinkedVisibleTimeAnchor(60), false);
  rendered = Number(playback.store.version);
  assert.equal(surface.setLinkedVisibleTimeAnchor(60), true);
});

test("viewport readiness catches up after parent publication, and teardown fences an already queued callback", async () => {
  const playback = new HistoryStudyPlayback(study(), 180_000);
  let ready!: (generation: number) => void, delivered = 0, released = false;
  const actions = { subscribeLinkedViewportReady: (callback: typeof ready) => { ready = callback; return () => { released = true; }; } } as ChartSurfaceActions;
  const surface = createStudyLinkSurface(playback, () => Number(playback.store.version), actions);
  const release = surface.subscribeLinkedViewportReady!(() => { delivered += 1; });
  ready(1); assert.equal(delivered, 0);
  await Promise.resolve(); assert.equal(delivered, 1);
  ready(2); release(); await Promise.resolve();
  assert.equal(delivered, 1); assert.equal(released, true);
});
