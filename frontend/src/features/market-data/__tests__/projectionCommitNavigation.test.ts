import assert from "node:assert/strict";
import test from "node:test";
import { createProjectionCommitGate } from "../../../chart-adapter/projectionCommitGate.js";
import { createChartDisplaySubscription } from "../chartDisplaySubscription.js";
import { ChartWorkScheduler } from "../chartWorkScheduler.js";
import { MarketWindowRegistry } from "../window/marketWindowSession.js";
import type { SeriesWindowView } from "../window/seriesWindowView.js";

const rows = (start: number, count: number) => Array.from({ length: count }, (_, i) => ({
  time: (start + i) * 60, open: 1, high: 3, low: 0, close: 2, volume: 1, is_closed: true,
}));

for (const hidden of [false, true]) test(`return to latest waits for the replaced projection (hidden=${hidden})`, () => {
  const frames = new Map<number, () => void>();
  let frameId = 0;
  const scheduler = new ChartWorkScheduler({
    maxFrameTasksPerFrame: 1,
    requestFrame: cb => { frames.set(++frameId, cb); return frameId; },
    cancelFrame: id => { frames.delete(id); },
  });
  scheduler.registerCell("a", hidden ? "hidden" : "visible-secondary");
  scheduler.registerCell("b", "focused");
  const owner = new MarketWindowRegistry().createWindow("a"), selection = owner.prepareSelection("btc");
  owner.activate(selection);
  owner.transact(selection, () => {
    owner.getOrCreate("btc");
    owner.apply("btc", { type: "replace", rows: rows(1, 10_000) });
  });
  const reader = owner.get("btc")!;
  const display = createChartDisplaySubscription(reader, { scheduler, cellId: "a" }, "main");
  const gate = createProjectionCommitGate<SeriesWindowView>();
  let displayedRows = reader.snapshot().slice(), latestVisible = false, navigationCount = 0;
  gate.didCommit(reader, reader.version);
  display.subscribe((_delta, source) => {
    displayedRows = source.snapshot().slice();
    // Models the existing historical-anchor compensation during replacement.
    latestVisible = false;
    gate.didCommit(source, source.version);
  });
  const flush = () => {
    const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(cb => cb());
  };
  scheduler.enqueueFrame("b", "candle-display", "busy", () => {});
  owner.transact(selection, () => owner.apply("btc", { type: "replace", rows: rows(10_001, 1500) }));
  gate.request(reader, reader.version, () => {
    assert.equal(displayedRows.length, 1500);
    assert.equal(displayedRows.at(-1)?.time, 11_500 * 60);
    latestVisible = true; navigationCount += 1;
  });
  flush(); // Another chart consumes the frame, or A remains hidden.
  assert.equal(navigationCount, 0, "one RAF after admission is not a display receipt");
  if (hidden) {
    assert.equal(frames.size, 0, "hidden navigation does not spin frames");
    scheduler.setCellTier("a", "focused");
  }
  flush();
  assert.equal(latestVisible, true);
  assert.equal(navigationCount, 1);
  flush();
  assert.equal(navigationCount, 1, "restoration needs no new tick and executes once");
});

test("projection receipts fence owner identity and failed/older renders", () => {
  const gate = createProjectionCommitGate<object>(), a = {}, b = {};
  let applied = 0;
  gate.request(a, 3, () => applied++);
  gate.didCommit(b, 9);
  gate.didCommit(a, 2);
  assert.equal(applied, 0);
  // A failed projection sends no receipt; the later successful coalesced version does.
  gate.didCommit(a, 4);
  assert.equal(applied, 1);
  gate.request(a, 4, () => applied++);
  assert.equal(applied, 2, "promise settlement after display applies immediately");
});

test("new navigation and surface reset retire pending viewport intents", () => {
  const gate = createProjectionCommitGate<object>(), owner = {};
  let applied = 0;
  gate.request(owner, 2, () => applied++);
  gate.cancel();
  gate.didCommit(owner, 2);
  assert.equal(applied, 0);
  gate.request(owner, 3, () => applied++);
  gate.reset();
  gate.didCommit(owner, 3);
  assert.equal(applied, 0);
  gate.reset();
  gate.request(owner, 3, () => applied++);
  assert.equal(applied, 0, "a remounted surface must render even the same owner/version again");
  gate.didCommit(owner, 3);
  assert.equal(applied, 1);
});
