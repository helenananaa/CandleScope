import assert from "node:assert/strict";
import test from "node:test";

import {
  bindSurfaceViewportSourceAnchor,
  buildSurfaceViewportSnapshot,
  planSurfaceViewportRestore,
  preserveBoundSurfaceViewportSourceAnchor,
  rememberSurfaceViewport,
  selectSurfaceViewportSnapshot,
  selectPeriodViewportRestore,
  surfaceViewportOwnsRestore,
  surfaceViewportHasAnchorCoverage,
  sourceRangeFromLogicalRows,
  transferSurfaceViewportSnapshot,
} from "../surfaceViewportState.js";
import type {
  OrdinalAxisTime,
  SurfaceViewportSnapshot,
} from "../chartRepresentationTypes.js";
import { IdentityProjector } from "../projectors/identityProjector.js";
import { aggregateReplayBaseBars } from "../../replay/replayViewerProjection.js";
import type { KlineBar } from "../../market-data/marketDataTypes.js";
import { mustBeDefined, partialMock } from "../../../test/testHelpers.js";

function ordinal(order: number, sourceTime: number, sourceOrdinal = 0): OrdinalAxisTime {
  return { order, sourceTime, sourceOrdinal };
}

test("a period round trip with initially unloaded ordinal history preserves its real anchor and density", () => {
  const rows = [1000, 10000, 11000].map((time, index) => ({ time: ordinal(index, time) }));
  const original = mustBeDefined(buildSurfaceViewportSnapshot({ datasetKey: "7m", axisMode: "derived-ordinal",
    surfaceConfigKey: "point-and-figure", displayRows: rows, barSpacing: 8,
    logicalRange: { from: -3, to: 5 }, sourceRange: sourceRangeFromLogicalRows(rows, { from: -3, to: 5 }, "1m") }));
  assert.equal(original.estimatedLeftEdge, true);
  const incoming = { ...original, anchorTime: original.anchorSourceTime, transferredFromDatasetKey: "90m" };
  const hydrated = [100, 1000, 10000, 11000].map((time, index) => ({ time: ordinal(index, time) }));
  const options = { datasetKey: "7m", axisMode: "derived-ordinal", surfaceConfigKey: "point-and-figure", sourceInterval: "1m" };
  const oldPlan = mustBeDefined(planSurfaceViewportRestore(hydrated, incoming, options));
  assert.notEqual(oldPlan.logicalRange.to - oldPlan.logicalRange.from, 8,
    "treating an estimated left-edge date as real history changes the zoom");
  const selected = mustBeDefined(selectPeriodViewportRestore(incoming, original));
  assert.equal(surfaceViewportOwnsRestore(selected), true, "geometry ownership must survive late main and auxiliary hydration");
  const restored = mustBeDefined(planSurfaceViewportRestore(hydrated, selected, options));
  assert.deepEqual(restored.logicalRange, { from: -2, to: 6 });
  assert.equal(restored.barSpacing, 8);
  const captured = mustBeDefined(buildSurfaceViewportSnapshot({ ...options, displayRows: hydrated,
    logicalRange: restored.logicalRange, sourceRange: sourceRangeFromLogicalRows(hydrated, restored.logicalRange, "1m") }));
  const bound = mustBeDefined(bindSurfaceViewportSourceAnchor(captured, selected));
  assert.deepEqual(bound.sourceRange, captured.sourceRange,
    "newly loaded history replaces an old estimated edge instead of reusing its guessed date");
  const sparseCapture = { ...captured, anchorTime: ordinal(0, 100), anchorSourceTime: 100, screenOffset: -50 };
  const sparseBound = mustBeDefined(bindSurfaceViewportSourceAnchor(sparseCapture, selected));
  assert.equal(surfaceViewportOwnsRestore(sparseBound), true);
  assert.deepEqual(planSurfaceViewportRestore(hydrated, sparseBound, options)?.logicalRange, restored.logicalRange,
    "a sparse intermediate capture cannot replace the original real anchor or offset");
  assert.equal(preserveBoundSurfaceViewportSourceAnchor(captured, sparseBound), captured,
    "the next period command captures real dates after hydration");
  const navigated = { ...incoming, sourceRange: { from: 1001, to: 12000 } };
  assert.equal(selectPeriodViewportRestore(navigated, original), navigated, "new navigation must win over the cached view");
  assert.equal(selectPeriodViewportRestore(incoming, { ...original, estimatedLeftEdge: false }), incoming,
    "fully covered views still preserve elapsed dates");
});

test("an owned period window survives internal axis rebasing until navigation releases it", () => {
  const bound: SurfaceViewportSnapshot = { anchorSourceTime: 1800, anchorTime: ordinal(18, 1800),
    barSpacing: 20, datasetKey: "ltc-90m", surfaceConfigKey: "line-break", axisMode: "derived-ordinal",
    logicalSpan: 8, screenOffset: -8, sourceRange: { from: 1600, to: 2400 }, transferredFromDatasetKey: "ltc-7m" };
  const rebased: SurfaceViewportSnapshot = { ...bound, anchorTime: ordinal(1, 100), anchorSourceTime: 100,
    logicalSpan: 4, screenOffset: 0, sourceRange: { from: 0, to: 400 } };
  const retained = mustBeDefined(preserveBoundSurfaceViewportSourceAnchor(rebased, bound));
  assert.deepEqual(retained.sourceRange, bound.sourceRange);
  assert.equal(retained.anchorSourceTime, 1800);
  assert.equal(retained.transferredFromDatasetKey, "ltc-7m");
  assert.equal(preserveBoundSurfaceViewportSourceAnchor(rebased, null), rebased, "user navigation clears the owned bound");
  assert.equal(preserveBoundSurfaceViewportSourceAnchor({ ...rebased, datasetKey: "sol-90m" }, bound)?.anchorSourceTime, 100,
    "the bound must not cross a market/dataset boundary");
});

test("numeric viewport capture preserves fractional edges and whitespace across period round trips", () => {
  const fine = Array.from({ length: 11 }, (_, index) => ({ time: index * 60 }));
  const sourceRange = mustBeDefined(sourceRangeFromLogicalRows(fine, { from: 2.5, to: 12.25 }, "1m"));
  assert.deepEqual(sourceRange, { from: 150, to: 735 });
  const coarse = Array.from({ length: 4 }, (_, index) => ({ time: index * 300 }));
  const snapshot = mustBeDefined(buildSurfaceViewportSnapshot({ axisMode: "time", datasetKey: "fine",
    displayRows: fine, logicalRange: { from: 2.5, to: 12.25 }, sourceRange, surfaceConfigKey: "time" }));
  const transferred = transferSurfaceViewportSnapshot(snapshot, { fromDatasetKey: "fine", toDatasetKey: "coarse" });
  const plan = mustBeDefined(planSurfaceViewportRestore(coarse, transferred, { axisMode: "time", datasetKey: "coarse", surfaceConfigKey: "time" }));
  assert.deepEqual(plan.logicalRange, { from: 0.5, to: 2.45 });
  assert.deepEqual(sourceRangeFromLogicalRows(coarse, plan.logicalRange, "5m"), sourceRange);
});

test("a linked numeric source window survives late history in the same dataset", () => {
  const late = Array.from({ length: 128 }, (_, index) => ({ time: (512 + index) * 300 }));
  const owned = mustBeDefined(buildSurfaceViewportSnapshot({ axisMode: "time", datasetKey: "ha-5m",
    displayRows: late, logicalRange: { from: 0, to: 38 }, surfaceConfigKey: "heikin-ashi" }));
  const sourceRange = { from: 440 * 300, to: 550 * 300 };
  const snapshot = { ...owned, sourceRange, preserveSourceRange: true };
  const options = { axisMode: "time", datasetKey: "ha-5m", surfaceConfigKey: "heikin-ashi", sourceInterval: "5m" };
  assert.deepEqual(planSurfaceViewportRestore(late, snapshot, options)?.logicalRange, { from: -72, to: 38 });
  const hydrated = Array.from({ length: 640 }, (_, index) => ({ time: index * 300 }));
  const range = mustBeDefined(planSurfaceViewportRestore(hydrated, snapshot, options)).logicalRange;
  assert.deepEqual(range, { from: 440, to: 550 });
  assert.deepEqual(sourceRangeFromLogicalRows(hydrated, range, "5m"), sourceRange);
});

test("calendar whitespace capture extrapolates actual month boundaries rather than February's length", () => {
  const rows = [0, 1].map(month => ({ time: Date.UTC(2024, month, 1) / 1000 }));
  const sourceRange = sourceRangeFromLogicalRows(rows, { from: -1, to: 3.5 }, "1M");
  assert.deepEqual(sourceRangeFromLogicalRows(rows, { from: -1, to: 3 }, "1M"),
    { from: Date.UTC(2023, 11, 1) / 1000, to: Date.UTC(2024, 3, 1) / 1000 });
  const snapshot = mustBeDefined(buildSurfaceViewportSnapshot({ axisMode: "time", datasetKey: "old",
    displayRows: rows, logicalRange: { from: -1, to: 3.5 }, sourceRange, surfaceConfigKey: "time" }));
  const transferred = transferSurfaceViewportSnapshot(snapshot, { fromDatasetKey: "old", toDatasetKey: "new" });
  assert.deepEqual(planSurfaceViewportRestore(rows, transferred,
    { axisMode: "time", datasetKey: "new", surfaceConfigKey: "time", sourceInterval: "1M" })?.logicalRange,
    { from: -1, to: 3.5 });
});

test("period transfer preserves absolute elapsed time instead of candle count", () => {
  const initial = mustBeDefined(buildSurfaceViewportSnapshot({ axisMode: "time", datasetKey: "btc-1m",
    displayRows: Array.from({ length: 61 }, (_, i) => ({ time: i * 60 })),
    logicalRange: { from: 7, to: 56 }, sourceRange: { from: 420, to: 3360 }, surfaceConfigKey: "time" }));
  const transfer = mustBeDefined(transferSurfaceViewportSnapshot(initial, { fromDatasetKey: "btc-1m", toDatasetKey: "btc-7m" }));
  const plan = mustBeDefined(planSurfaceViewportRestore(Array.from({ length: 10 }, (_, i) => ({ time: i * 420 })), transfer,
    { axisMode: "time", datasetKey: "btc-7m", surfaceConfigKey: "time" }));
  assert.deepEqual(plan.logicalRange, { from: 1, to: 8 });
  assert.equal(plan.barSpacing, null);
});

test("cross-surface restore bounds sparse synthetic density to available columns", () => {
  const sourceRows = Array.from({ length: 121 }, (_, index) => ({ time: index }));
  const snapshot = buildSurfaceViewportSnapshot({
    axisMode: "time",
    barSpacing: 5,
    datasetKey: "btc-1h",
    displayRows: sourceRows,
    logicalRange: { from: 0, to: 120 },
    surfaceConfigKey: "time",
  });
  const renkoRows = [0, 20, 40, 60, 80, 100, 110, 120].map((sourceTime, index) => ({
    time: ordinal(index, sourceTime, 0),
  }));

  const plan = planSurfaceViewportRestore(renkoRows, snapshot, {
    axisMode: "derived-ordinal",
    datasetKey: "btc-1h",
    surfaceConfigKey: "derived-ordinal:renko",
  });

  const restorePlan = mustBeDefined(plan);
  assert.deepEqual(restorePlan.logicalRange, { from: -1, to: 7 });
  assert.equal(
    mustBeDefined(restorePlan.logicalRange).to - mustBeDefined(restorePlan.logicalRange).from,
    8,
  );
  assert.equal(restorePlan.barSpacing, null);
  assert.equal(restorePlan.sameSurface, false);
});

test("surface snapshots preserve future right whitespace through anchor offsets", () => {
  const sourceRows = Array.from({ length: 100 }, (_, index) => ({ time: index }));
  const snapshot = buildSurfaceViewportSnapshot({
    axisMode: "time",
    datasetKey: "btc-1h",
    displayRows: sourceRows,
    logicalRange: { from: 5, to: 125 },
    surfaceConfigKey: "time",
  });
  const targetRows = [0, 15, 30, 45, 60, 75, 90, 99].map((sourceTime, index) => ({
    time: ordinal(index, sourceTime, 0),
  }));
  const plan = planSurfaceViewportRestore(targetRows, snapshot, {
    axisMode: "derived-ordinal",
    datasetKey: "btc-1h",
    surfaceConfigKey: "derived-ordinal:renko",
  });

  assert.equal(mustBeDefined(snapshot).screenOffset, -26);
  const range = mustBeDefined(mustBeDefined(plan).logicalRange);
  assert.ok(Math.abs((range.to - range.from) - 8) < 1e-9);
  assert.ok(Math.abs(range.to - 7 - 26 * 8 / 120) < 1e-9);
});

test("same ordinal surface restores the exact repeated-source brick", () => {
  const rows = [
    { time: ordinal(0, 100, 0) },
    { time: ordinal(1, 100, 1) },
    { time: ordinal(2, 200, 0) },
  ];
  const snapshot = buildSurfaceViewportSnapshot({
    axisMode: "derived-ordinal",
    barSpacing: 9,
    datasetKey: "btc-1h",
    displayRows: rows,
    logicalRange: { from: -2, to: 0 },
    surfaceConfigKey: "derived-ordinal:renko",
  });
  const plan = planSurfaceViewportRestore(rows, snapshot, {
    axisMode: "derived-ordinal",
    datasetKey: "btc-1h",
    surfaceConfigKey: "derived-ordinal:renko",
  });

  const restorePlan = mustBeDefined(plan);
  assert.deepEqual(restorePlan.logicalRange, { from: -2, to: 0 });
  assert.equal(restorePlan.barSpacing, 9);
  assert.equal(restorePlan.sameSurface, true);
});

test("surface cache prefers the target's remembered viewport and isolates datasets", () => {
  const cache = new Map<string, SurfaceViewportSnapshot>();
  const timeSnapshot = partialMock<SurfaceViewportSnapshot>({
    axisMode: "time",
    datasetKey: "btc-1h",
    surfaceConfigKey: "time",
  });
  const renkoSnapshot = partialMock<SurfaceViewportSnapshot>({
    axisMode: "derived-ordinal",
    datasetKey: "btc-1h",
    surfaceConfigKey: "derived-ordinal:renko",
  });
  assert.equal(rememberSurfaceViewport(cache, timeSnapshot), true);
  assert.equal(rememberSurfaceViewport(cache, renkoSnapshot), true);

  assert.deepEqual(selectSurfaceViewportSnapshot(cache, {
    datasetKey: "btc-1h",
    outgoingSnapshot: renkoSnapshot,
    surfaceConfigKey: "time",
  }), { snapshot: timeSnapshot, source: "remembered" });
  assert.deepEqual(selectSurfaceViewportSnapshot(cache, {
    datasetKey: "eth-1h",
    outgoingSnapshot: renkoSnapshot,
    surfaceConfigKey: "time",
  }), { snapshot: null, source: "none" });
});

test("surface cache evicts the oldest entry at its bound", () => {
  const cache = new Map<string, SurfaceViewportSnapshot>();
  for (let index = 0; index < 3; index += 1) {
    rememberSurfaceViewport(cache, partialMock<SurfaceViewportSnapshot>({
      datasetKey: `dataset-${index}`,
      surfaceConfigKey: "time",
    }), { limit: 2 });
  }

  assert.equal(cache.size, 2);
  assert.equal([...cache.keys()].some((key) => key.includes("dataset-0")), false);
});

test("an explicit dataset transition rebinds only the owned outgoing viewport", () => {
  const snapshot = partialMock<SurfaceViewportSnapshot>({
    anchorSourceTime: 1_700_000_000,
    datasetKey: "replay-base|viewer:1m",
    logicalSpan: 120,
    screenOffset: -4,
    surfaceConfigKey: "time",
  });

  assert.deepEqual(transferSurfaceViewportSnapshot(snapshot, {
    fromDatasetKey: "replay-base|viewer:1m",
    toDatasetKey: "replay-base|viewer:5m",
  }), {
    ...snapshot,
    anchorTime: snapshot.anchorSourceTime,
    transferredFromDatasetKey: "replay-base|viewer:1m",
    datasetKey: "replay-base|viewer:5m",
  });
  assert.equal(transferSurfaceViewportSnapshot(snapshot, {
    fromDatasetKey: "another-dataset",
    toDatasetKey: "replay-base|viewer:5m",
  }), null);
  assert.equal(transferSurfaceViewportSnapshot(snapshot, {
    fromDatasetKey: "replay-base|viewer:1m",
    toDatasetKey: "replay-base|viewer:1m",
  }), null);
});

test("dataset viewport transfer waits until target rows cover its source anchor", () => {
  const snapshot = partialMock<SurfaceViewportSnapshot>({
    anchorSourceTime: 20,
    datasetKey: "replay-base|viewer:1m",
  });

  assert.equal(surfaceViewportHasAnchorCoverage([
    { time: 30 },
    { time: 40 },
  ], snapshot), false);
  assert.equal(surfaceViewportHasAnchorCoverage([
    { time: 5 },
    { time: 20 },
    { time: 30 },
  ], snapshot), true);
  assert.equal(surfaceViewportHasAnchorCoverage([], snapshot), false);
});

test("a forming coarse replay bucket preserves an in-bucket anchor round trip", () => {
  const start = Date.UTC(2026, 6, 1, 12, 0) / 1_000;
  const baseRows: KlineBar[] = Array.from({ length: 8 }, (_, index) => ({
    time: (start + index * 60) as KlineBar["time"],
    open: 100 + index,
    high: 101 + index,
    low: 99 + index,
    close: 100.5 + index,
    volume: 1,
    sourceFromTime: start + index * 60,
    sourceToTime: start + index * 60,
    replayClosed: true,
  }));
  const identity = new IdentityProjector();
  const fineRows = identity.project(baseRows);
  const initial = mustBeDefined(buildSurfaceViewportSnapshot({
    axisMode: "time",
    datasetKey: "viewer:1m",
    displayRows: fineRows,
    logicalRange: { from: -43, to: 57 },
    surfaceConfigKey: "time",
  }));
  assert.equal(initial.anchorSourceTime, start + 7 * 60);

  const coarseRows = identity.project(
    aggregateReplayBaseBars(baseRows, "1m", "15m"),
  );
  const coarseTransfer = mustBeDefined(transferSurfaceViewportSnapshot(initial, {
    fromDatasetKey: "viewer:1m",
    toDatasetKey: "viewer:15m",
  }));
  assert.equal(surfaceViewportHasAnchorCoverage(coarseRows, coarseTransfer), true);
  const coarsePlan = mustBeDefined(planSurfaceViewportRestore(coarseRows, coarseTransfer, {
    axisMode: "time",
    datasetKey: "viewer:15m",
    surfaceConfigKey: "time",
  }));
  assert.deepEqual(coarsePlan.logicalRange, { from: -50, to: 50 });

  const coarseSnapshot = mustBeDefined(buildSurfaceViewportSnapshot({
    axisMode: "time",
    datasetKey: "viewer:15m",
    displayRows: coarseRows,
    logicalRange: coarsePlan.logicalRange,
    surfaceConfigKey: "time",
  }));
  assert.equal(coarseSnapshot.anchorSourceTime, start + 7 * 60);
  const fineTransfer = mustBeDefined(transferSurfaceViewportSnapshot(coarseSnapshot, {
    fromDatasetKey: "viewer:15m",
    toDatasetKey: "viewer:1m",
  }));
  const finePlan = mustBeDefined(planSurfaceViewportRestore(fineRows, fineTransfer, {
    axisMode: "time",
    datasetKey: "viewer:1m",
    surfaceConfigKey: "time",
  }));
  assert.deepEqual(finePlan.logicalRange, { from: -43, to: 57 });
});

test("a complete coarse bucket keeps the original in-bucket anchor across recapture", () => {
  const start = Date.UTC(2026, 6, 1, 12, 0) / 1_000;
  const baseRows: KlineBar[] = Array.from({ length: 15 }, (_, index) => ({
    time: (start + index * 60) as KlineBar["time"],
    open: 100 + index,
    high: 101 + index,
    low: 99 + index,
    close: 100.5 + index,
    volume: 1,
    sourceFromTime: start + index * 60,
    sourceToTime: start + index * 60,
    replayClosed: true,
  }));
  const fineRows = new IdentityProjector().project(baseRows);
  const initial = mustBeDefined(buildSurfaceViewportSnapshot({
    axisMode: "time",
    datasetKey: "viewer:1m",
    displayRows: fineRows,
    logicalRange: { from: -93, to: 7 },
    surfaceConfigKey: "time",
  }));
  assert.equal(initial.anchorSourceTime, start + 7 * 60);

  const coarseRows = new IdentityProjector().project(
    aggregateReplayBaseBars(baseRows, "1m", "15m"),
  );
  const transfer = mustBeDefined(transferSurfaceViewportSnapshot(initial, {
    fromDatasetKey: "viewer:1m",
    toDatasetKey: "viewer:15m",
  }));
  const plan = mustBeDefined(planSurfaceViewportRestore(coarseRows, transfer, {
    axisMode: "time",
    datasetKey: "viewer:15m",
    surfaceConfigKey: "time",
  }));
  const rawCoarseCapture = mustBeDefined(buildSurfaceViewportSnapshot({
    axisMode: "time",
    datasetKey: "viewer:15m",
    displayRows: coarseRows,
    logicalRange: plan.logicalRange,
    surfaceConfigKey: "time",
  }));
  assert.equal(rawCoarseCapture.anchorSourceTime, start + 14 * 60);

  const boundCapture = mustBeDefined(bindSurfaceViewportSourceAnchor(
    rawCoarseCapture,
    transfer,
  ));
  assert.equal(boundCapture.anchorSourceTime, start + 7 * 60);
  const nextCapture = mustBeDefined(preserveBoundSurfaceViewportSourceAnchor(
    rawCoarseCapture,
    boundCapture,
  ));
  assert.equal(nextCapture.anchorSourceTime, start + 7 * 60);

  const fineTransfer = mustBeDefined(transferSurfaceViewportSnapshot(nextCapture, {
    fromDatasetKey: "viewer:15m",
    toDatasetKey: "viewer:1m",
  }));
  const finePlan = mustBeDefined(planSurfaceViewportRestore(fineRows, fineTransfer, {
    axisMode: "time",
    datasetKey: "viewer:1m",
    surfaceConfigKey: "time",
  }));
  assert.deepEqual(finePlan.logicalRange, { from: -93, to: 7 });
});

test("viewport coverage rejects an anchor inside an internal source gap", () => {
  const snapshot = partialMock<SurfaceViewportSnapshot>({
    anchorSourceTime: 15,
    datasetKey: "viewer:1m",
  });
  assert.equal(surfaceViewportHasAnchorCoverage([
    { time: 0, sourceFromTime: 0, sourceToTime: 10 },
    { time: 20, sourceFromTime: 20, sourceToTime: 30 },
  ], snapshot), false);
});

test("period transfer accepts an interior bucket anchor without bridging missing candles", () => {
  const snapshot = partialMock<SurfaceViewportSnapshot>({ anchorSourceTime: 7 * 60 });
  assert.equal(surfaceViewportHasAnchorCoverage([{ time: 5 * 60 }], snapshot, { sourceInterval: "5m" }), true);
  assert.equal(surfaceViewportHasAnchorCoverage([{ time: 0 }, { time: 10 * 60 }], snapshot, { sourceInterval: "5m" }), false);
  assert.equal(surfaceViewportHasAnchorCoverage([{ time: 5 * 60 }],
    { ...snapshot, anchorSourceTime: 10 * 60 }, { sourceInterval: "5m" }), false);
  assert.equal(surfaceViewportHasAnchorCoverage([{ time: 5 * 60 }], snapshot), false);
});

test("calendar coverage uses the actual leap-year month end and explicit lineage wins", () => {
  const feb = Date.UTC(2024, 1, 1) / 1000;
  const march = Date.UTC(2024, 2, 1) / 1000;
  const snapshot = partialMock<SurfaceViewportSnapshot>({ anchorSourceTime: march - 60 });
  assert.equal(surfaceViewportHasAnchorCoverage([{ time: feb }], snapshot, { sourceInterval: "1M" }), true);
  assert.equal(surfaceViewportHasAnchorCoverage([{ time: feb }], { ...snapshot, anchorSourceTime: march }, { sourceInterval: "1M" }), false);
  assert.equal(surfaceViewportHasAnchorCoverage([{ time: feb, sourceFromTime: feb, sourceToTime: feb + 60 }], snapshot, { sourceInterval: "1M" }), false);
});


test("sparse ordinal dataset transfer adapts spacing but exact-surface zoom is retained", () => {
  const rows = Array.from({ length: 8 }, (_, index) => ({ time: ordinal(index, index * 60) }));
  const snapshot = mustBeDefined(buildSurfaceViewportSnapshot({
    axisMode: "derived-ordinal", datasetKey: "fine", displayRows: rows,
    surfaceConfigKey: "derived-ordinal:renko", logicalRange: { from: -113, to: 7 }, barSpacing: 5,
  }));
  const original = mustBeDefined(planSurfaceViewportRestore(rows, snapshot, {
    axisMode: "derived-ordinal", datasetKey: "fine", surfaceConfigKey: "derived-ordinal:renko",
  }));
  assert.deepEqual(original.logicalRange, { from: -113, to: 7 });
  assert.equal(original.barSpacing, 5);
  const transfer = transferSurfaceViewportSnapshot(snapshot, { fromDatasetKey: "fine", toDatasetKey: "coarse" });
  const adapted = mustBeDefined(planSurfaceViewportRestore(rows, transfer, {
    axisMode: "derived-ordinal", datasetKey: "coarse", surfaceConfigKey: "derived-ordinal:renko",
  }));
  assert.deepEqual(adapted.logicalRange, { from: -1, to: 7 });
  assert.equal(adapted.barSpacing, null);
});
