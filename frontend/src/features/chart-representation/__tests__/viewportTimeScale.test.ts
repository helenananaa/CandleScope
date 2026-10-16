import assert from "node:assert/strict";
import test from "node:test";
import { createViewportTimeScale } from "../viewportTimeScale.js";
import { mustBeDefined } from "../../../test/testHelpers.js";

const ordinal = (times: number[]) => times.map((sourceTime, order) => ({ time: { order, sourceTime, sourceOrdinal: order } }));

test("ordinal visible time uses axis identity rather than a long leg lineage", () => {
  const rows = ordinal([600, 1200, 1800]).map(row => ({ ...row, sourceFromTime: 0, sourceToTime: row.time.sourceTime + 360 }));
  const scale = mustBeDefined(createViewportTimeScale(rows, "7m"));
  assert.deepEqual(scale.sourceRange({ from: 0.5, to: 1.5 }), { from: 900, to: 1500 });
  assert.deepEqual(scale.logicalRange({ from: 900, to: 1500 }), { from: 0.5, to: 1.5 });
});

test("multiple bricks at one time are retained at linked viewport edges", () => {
  const scale = mustBeDefined(createViewportTimeScale(ordinal([60, 60, 60, 120, 180, 180]), "1m"));
  assert.deepEqual(scale.logicalRange({ from: 60, to: 180 }), { from: 0, to: 5 });
  assert.deepEqual(scale.logicalRange({ from: 90, to: 150 }), { from: 2.5, to: 3.5 });
  assert.deepEqual(scale.sourceRange({ from: 0.5, to: 1.5 }), { from: 60, to: 60 });
});

test("future ordinal whitespace starts at the revealed horizon, not the last emitted brick", () => {
  const rows = ordinal([0, 60]);
  // No brick emitted for many source periods. Render-only carriers resume
  // after the source horizon; they occupy real logical positions after rows.
  const carriers = ordinal([660, 720, 780]);
  const scale = mustBeDefined(createViewportTimeScale(rows, "1m", carriers));
  assert.deepEqual(scale.sourceRange({ from: 1.5, to: 3.5 }), { from: 360, to: 750 });
  assert.deepEqual(scale.logicalRange({ from: 360, to: 750 }), { from: 1.5, to: 3.5 });
  assert.deepEqual(scale.sourceRange({ from: 3.5, to: 5.5 }), { from: 750, to: 870 });
});

test("calendar axis edges preserve actual months across leap February", () => {
  const jan = Date.UTC(2024, 0, 1) / 1000, feb = Date.UTC(2024, 1, 1) / 1000;
  const scale = mustBeDefined(createViewportTimeScale(ordinal([jan, feb]), "1M"));
  const range = { from: -1, to: 3.5 };
  const time = mustBeDefined(scale.sourceRange(range));
  assert.equal(time.from, Date.UTC(2023, 11, 1) / 1000);
  assert.equal(time.to, Date.UTC(2024, 3, 16) / 1000);
  assert.deepEqual(scale.logicalRange(time), range);
});

test("non-monotonic projection identity is rejected instead of inventing elapsed view time", () => {
  assert.equal(createViewportTimeScale(ordinal([60, 180, 120]), "1m"), null);
  assert.equal(createViewportTimeScale(ordinal([60, 120]), "1m", ordinal([90, 180])), null);
});

test("one loaded synthetic output can retain a range while history is pending", () => {
  const scale = mustBeDefined(createViewportTimeScale(ordinal([1200]), "1m"));
  const range = { from: 900, to: 1290 };
  const logical = mustBeDefined(scale.logicalRange(range));
  assert.deepEqual(scale.sourceRange(logical), range);
});
