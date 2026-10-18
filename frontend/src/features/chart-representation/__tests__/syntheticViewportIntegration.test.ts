import assert from "node:assert/strict";
import test from "node:test";
import { aggregateReplayBaseBars } from "../../replay/replayViewerProjection.js";
import type { KlineBar } from "../../market-data/marketDataTypes.js";
import type { DisplayRow, Projector } from "../chartRepresentationTypes.js";
import { RenkoProjector } from "../projectors/renkoProjector.js";
import { PointFigureProjector } from "../projectors/pointFigureProjector.js";
import { KagiProjector } from "../projectors/kagiProjector.js";
import { LineBreakProjector } from "../projectors/lineBreakProjector.js";
import { bindSurfaceViewportSourceAnchor, buildSurfaceViewportSnapshot, planSurfaceViewportRestore,
  sourceRangeFromLogicalRows, transferSurfaceViewportSnapshot } from "../surfaceViewportState.js";
import { createViewportTimeScale } from "../viewportTimeScale.js";
import { TransferredViewportHistory } from "../../../components/transferredViewportHistory.js";
import { mustBeDefined } from "../../../test/testHelpers.js";

const minuteBars: KlineBar[] = Array.from({ length: 21 * 1440 }, (_, index) => {
  const close = 100 + 4 * Math.sin(index / 80) + 8 * Math.sin(index / 1700);
  return { time: (Date.UTC(2026, 8, 20) / 1000 + index * 60) as KlineBar["time"],
    open: close, high: close, low: close, close, volume: 2, replayClosed: true, is_closed: true };
});
const source7 = [...aggregateReplayBaseBars(minuteBars, "1m", "7m")];
const source90 = [...aggregateReplayBaseBars(minuteBars, "1m", "90m")];
const projectors: Array<() => Projector> = [
  () => new RenkoProjector({ boxSize: 0.25, minTick: 0.01 }),
  () => new PointFigureProjector({ boxSize: 0.25, minTick: 0.01, reversalAmount: 3 }),
  () => new KagiProjector({ reversalTicks: 75, minTick: 0.01 }),
  () => new LineBreakProjector({ numberOfLines: 3, minTick: 0.01 }),
];
function near(actual: number, expected: number, message: string) {
  assert.ok(Math.abs(actual - expected) < 0.001, `${message}: ${actual} != ${expected}`);
}
function capture(rows: readonly DisplayRow[], range: { from: number; to: number }, period: string, config: string) {
  return mustBeDefined(buildSurfaceViewportSnapshot({ datasetKey: period, surfaceConfigKey: config,
    axisMode: "derived-ordinal", displayRows: rows, logicalRange: range,
    sourceRange: mustBeDefined(sourceRangeFromLogicalRows(rows, range, period)) }));
}
for (const create of projectors) {
  if (["point-and-figure", "kagi"].includes(create().id)) test(`${create().id}: empty coarse seed keeps the transfer pending until history produces a surface`, () => {
    const fine = create().project(source7);
    const config = `derived-ordinal:${create().id}`;
    const initial = capture(fine, { from: fine.length - 37.25, to: fine.length - 3.5 }, "7m", config);
    const transfer = mustBeDefined(transferSurfaceViewportSnapshot(initial, { fromDatasetKey: "7m", toDatasetKey: "90m" }));
    const seed = create().project(source90.slice(-1));
    assert.equal(seed.length, 0);
    const options = { datasetKey: "90m", axisMode: "derived-ordinal", sourceInterval: "90m", surfaceConfigKey: config };
    // A null logical range passed to ViewportController means fitContent and
    // reports success. There must be no restore plan to settle at this stage.
    assert.equal(planSurfaceViewportRestore(seed, transfer, options), null);
    const hydrated = create().project(source90);
    const plan = mustBeDefined(planSurfaceViewportRestore(hydrated, transfer, options));
    const restored = mustBeDefined(sourceRangeFromLogicalRows(hydrated, plan.logicalRange, "90m"));
    near(restored.from, mustBeDefined(initial.sourceRange).from, "late history left edge");
    near(restored.to, mustBeDefined(initial.sourceRange).to, "late history right edge");
  });
  test(`${create().id}: linked ordinal view hydrates only its visible dates and retains the range`, () => {
    const full = create().project(source90);
    const seed = create().project(source90.slice(-8));
    const range = mustBeDefined(sourceRangeFromLogicalRows(full,
      { from: full.length - 20.25, to: full.length - 3.5 }, "90m"));
    const logical = mustBeDefined(createViewportTimeScale(seed, "90m")?.logicalRange(range));
    const bound = { ...capture(seed, logical, "90m", create().id), sourceRange: range, preserveSourceRange: true };
    const fill = new TransferredViewportHistory("90m", range.from);
    let count = 8;
    while (fill.claim({ datasetKey: "90m", firstTime: source90.at(-count)?.time,
      loading: false, canLoad: true, hasHandler: true }) !== null) {
      count += 16;
      fill.settle(true);
    }
    assert.ok(count < source90.length, "a linked date range must not demand the whole cumulative lineage");
    assert.ok(source90.at(-count)!.time <= range.from);
    const hydrated = create().project(source90.slice(-count));
    const restored = mustBeDefined(planSurfaceViewportRestore(hydrated, bound,
      { datasetKey: "90m", axisMode: "derived-ordinal", sourceInterval: "90m", surfaceConfigKey: create().id }));
    const actual = mustBeDefined(sourceRangeFromLogicalRows(hydrated, restored.logicalRange, "90m"));
    near(actual.from, range.from, "linked left time after prepend");
    near(actual.to, range.to, "linked right time after prepend");
  });
  test(`${create().id}: real 7m/90m period round trip and late history retain elapsed viewport`, () => {
    const fine = create().project(source7), coarse = create().project(source90);
    const config = `derived-ordinal:${create().id}`;
    const initial = capture(fine, { from: fine.length - 37.25, to: fine.length - 3.5 }, "7m", config);
    const transfer = mustBeDefined(transferSurfaceViewportSnapshot(initial, { fromDatasetKey: "7m", toDatasetKey: "90m" }));
    const seed = create().project(source90.slice(-8));
    const seedPlan = mustBeDefined(planSurfaceViewportRestore(seed, transfer,
      { datasetKey: "90m", axisMode: "derived-ordinal", sourceInterval: "90m", surfaceConfigKey: config }));
    const bound = mustBeDefined(bindSurfaceViewportSourceAnchor(capture(seed, mustBeDefined(seedPlan.logicalRange), "90m", config), transfer));
    // Hydration must reapply the original elapsed range, not the sparse seed's
    // number of bricks or the seed's estimated history dates.
    const hydrated = mustBeDefined(planSurfaceViewportRestore(coarse, bound,
      { datasetKey: "90m", axisMode: "derived-ordinal", sourceInterval: "90m", surfaceConfigKey: config }));
    const coarseCapture = capture(coarse, mustBeDefined(hydrated.logicalRange), "90m", config);
    near(mustBeDefined(coarseCapture.sourceRange).from, mustBeDefined(initial.sourceRange).from, "left time after history");
    near(mustBeDefined(coarseCapture.sourceRange).to, mustBeDefined(initial.sourceRange).to, "right time after history");
    const back = mustBeDefined(transferSurfaceViewportSnapshot(
      mustBeDefined(bindSurfaceViewportSourceAnchor(coarseCapture, transfer)),
      { fromDatasetKey: "90m", toDatasetKey: "7m" }));
    const plan = mustBeDefined(planSurfaceViewportRestore(fine, back,
      { datasetKey: "7m", axisMode: "derived-ordinal", sourceInterval: "7m", surfaceConfigKey: config }));
    const restored = capture(fine, mustBeDefined(plan.logicalRange), "7m", config);
    near(mustBeDefined(restored.sourceRange).from, mustBeDefined(initial.sourceRange).from, "round-trip left time");
    near(mustBeDefined(restored.sourceRange).to, mustBeDefined(initial.sourceRange).to, "round-trip right time");
  });
}
