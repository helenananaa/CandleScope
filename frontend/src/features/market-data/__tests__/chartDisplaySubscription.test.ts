import assert from "node:assert/strict";
import test from "node:test";
import { ChartWorkScheduler } from "../chartWorkScheduler.js";
import { createChartDisplaySubscription } from "../chartDisplaySubscription.js";
import { MarketWindowRegistry } from "../window/marketWindowSession.js";
import type { WindowDelta } from "../klineContracts.js";
import { ProjectionStore } from "../../chart-representation/projectionStore.js";
import { RenkoProjector } from "../../chart-representation/projectors/renkoProjector.js";

const row = (time: number, close = 1) => ({ time, open: 1, high: 5, low: 0, close, volume: 1, is_closed: false });
function fixture() {
  const frames = new Map<number, () => void>();
  let id = 0;
  // Frame timing is simulated here; host scheduling must not consume its budget.
  const scheduler = new ChartWorkScheduler({ now: () => 0, requestFrame: cb => { frames.set(++id, cb); return id; }, cancelFrame: handle => { frames.delete(handle); } });
  const registry = new MarketWindowRegistry();
  const cells = ["a", "b"].map(cellId => {
    scheduler.registerCell(cellId, cellId === "a" ? "focused" : "visible-secondary");
    const owner = registry.createWindow(cellId), selection = owner.prepareSelection("btc");
    owner.activate(selection);
    owner.transact(selection, () => { owner.getOrCreate("btc"); owner.apply("btc", { type: "replace", rows: [row(60), row(120)] }); });
    const reader = owner.get("btc")!;
    const display = createChartDisplaySubscription(reader, { scheduler, cellId }, "bars");
    const paints: { delta: WindowDelta; rows: number[]; close: number | undefined }[] = [];
    const release = display.subscribe((delta, source) => paints.push({ delta, rows: source.snapshot().map(bar => Number(bar.time)), close: source.last()?.close }));
    return { owner, selection, reader, display, paints, release };
  });
  return { scheduler, cells, frames, flush: () => { const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(cb => cb()); } };
}

test("both owners admit every event synchronously and render one final tail per frame", () => {
  const f = fixture();
  for (const cell of f.cells) {
    const hot = cell.reader.snapshot();
    let admissions = 0;
    cell.reader.subscribe(() => { admissions += 1; });
    for (const close of [2, 3, 4]) cell.owner.transact(cell.selection, () => cell.owner.apply("btc", { type: "tick", row: row(120, close) }));
    assert.equal(admissions, 3);
    assert.equal(cell.reader.last()?.close, 4);
    assert.equal(cell.reader.snapshot(), hot);
    assert.equal(cell.paints.length, 0);
  }
  f.flush();
  for (const cell of f.cells) {
    assert.equal(cell.paints.length, 1);
    assert.equal(cell.paints[0]?.delta.type, "tick");
    assert.equal(cell.paints[0]?.close, 4);
    assert.equal(cell.display.getSnapshot(), cell.reader.version);
  }
});

test("hidden structural changes and correctWindow deletions survive until visibility resumes without a tick", () => {
  const f = fixture(), a = f.cells[0]!, b = f.cells[1]!;
  f.scheduler.setCellTier("a", "hidden");
  a.owner.transact(a.selection, () => a.owner.apply("btc", { type: "tick", row: row(180) }));
  a.owner.transact(a.selection, () => a.owner.apply("btc", { type: "replace", rows: [row(60, 2), row(180, 3)] }));
  a.owner.transact(a.selection, () => a.owner.apply("btc", { type: "tick", row: row(180, 4) }));
  assert.deepEqual(a.reader.snapshot().map(bar => bar.time), [60, 180]);
  assert.deepEqual(b.reader.snapshot().map(bar => bar.time), [60, 120]);
  assert.equal(f.frames.size, 0, "hidden work must not spin RAF");
  f.scheduler.setWindowVisible(false);
  f.scheduler.setCellTier("a", "focused");
  assert.equal(f.frames.size, 0);
  f.scheduler.setWindowVisible(true);
  f.flush();
  assert.equal(a.paints.length, 1);
  assert.deepEqual(a.paints[0]?.rows, [60, 180]);
  assert.equal(a.paints[0]?.delta.type, "mid-merge");
  assert.equal(a.paints[0]?.close, 4);
  assert.equal(b.paints.length, 0);
});

test("a disposed display generation cannot paint or erase its replacement", () => {
  const f = fixture(), a = f.cells[0]!;
  a.owner.transact(a.selection, () => a.owner.apply("btc", { type: "tick", row: row(120, 2) }));
  a.release();
  const next = createChartDisplaySubscription(a.reader, { scheduler: f.scheduler, cellId: "a" }, "bars");
  let painted = 0;
  next.subscribe(() => { painted += 1; });
  a.owner.transact(a.selection, () => a.owner.apply("btc", { type: "tick", row: row(120, 3) }));
  f.flush();
  assert.equal(a.paints.length, 0);
  assert.equal(painted, 1);
});

test("coalesced structural recovery matches fresh candle and Renko projections", () => {
  const f = fixture(), a = f.cells[0]!;
  const projections = [new ProjectionStore(), new ProjectionStore({ projector: new RenkoProjector({ boxSize: 1, minTick: 1 }) })];
  for (const projection of projections) projection.reset(a.reader.snapshot());
  a.display.subscribe((delta, source) => {
    for (const projection of projections) projection.applySourceDelta(delta, source.snapshot());
  });
  f.scheduler.setWindowVisible(false);
  a.owner.transact(a.selection, () => a.owner.apply("btc", { type: "tick", row: row(180, 4) }));
  a.owner.transact(a.selection, () => a.owner.apply("btc", { type: "replace", rows: [row(60, 4), row(180, 2)] }));
  f.scheduler.setWindowVisible(true); f.flush();
  const expected = [new ProjectionStore(), new ProjectionStore({ projector: new RenkoProjector({ boxSize: 1, minTick: 1 }) })];
  expected.forEach((projection, index) => {
    projection.reset(a.reader.snapshot());
    assert.deepEqual(projections[index]!.displaySnapshot(), projection.displaySnapshot());
  });
});
