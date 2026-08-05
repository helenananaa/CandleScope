import assert from "node:assert/strict";
import test from "node:test";
import { buildChartNavigationWindow } from "../chartNavigationModel.js";
import type { DisplayRow } from "../../features/chart-representation/chartRepresentationTypes.js";

test("chart event navigation centers a bounded source-time window", () => {
  const rows = Array.from({ length: 100 }, (_, index) => ({
    time: 1_000 + index * 60,
  })) as DisplayRow[];
  const plan = buildChartNavigationWindow(rows, 1_000 + 70 * 60);

  assert.deepEqual(plan, {
    targetIndex: 70,
    logicalRange: { from: 10, to: 90 },
    timeRange: { from: 1_600, to: 6_400 },
  });
});

test("chart event navigation clamps edges and accepts a derived lineage range", () => {
  const rows = [
    { time: 100 },
    {
      time: { order: 1, sourceTime: 200, sourceOrdinal: 0 },
      customValues: { chartProjection: { sourceFromTime: 160, sourceToTime: 220 } },
    },
    { time: 300 },
  ] as DisplayRow[];
  const plan = buildChartNavigationWindow(rows, 180, { beforeBars: 60, afterBars: 20 });

  assert.equal(plan?.targetIndex, 1);
  assert.deepEqual(plan?.logicalRange, { from: 0, to: 2 });
  assert.deepEqual(plan?.timeRange, { from: 100, to: 300 });
  assert.equal(buildChartNavigationWindow(rows, 999), null);
});
