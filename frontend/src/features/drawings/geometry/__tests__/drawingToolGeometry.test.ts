import assert from "node:assert/strict";
import test from "node:test";
import {
  arrowHeadLengthCssPx,
  arrowHeadScreenGeometry,
  parallelChannelScreenGeometry,
  pointInScreenPolygon,
} from "../drawingToolGeometry.js";

test("parallel channel translates the baseline vertically through the third point", () => {
  const channel = parallelChannelScreenGeometry({ x: 10, y: 100 }, { x: 110, y: 50 }, { x: 60, y: 45 });
  assert.ok(channel);
  // Baseline y at x=60 is 75, so the parallel line sits 30px above it.
  assert.deepEqual(channel.parallel, [{ x: 10, y: 70 }, { x: 110, y: 20 }]);
  assert.deepEqual(channel.midline, [{ x: 10, y: 85 }, { x: 110, y: 35 }]);
  assert.deepEqual(channel.offsetHandle, { x: 60, y: 45 });
  const slope = (a: { x: number; y: number }, b: { x: number; y: number }) => (b.y - a.y) / (b.x - a.x);
  assert.equal(slope(channel.baseline[0], channel.baseline[1]), slope(channel.parallel[0], channel.parallel[1]));
});

test("a third point outside the baseline span extrapolates instead of clamping", () => {
  const channel = parallelChannelScreenGeometry({ x: 0, y: 0 }, { x: 10, y: 10 }, { x: 30, y: 20 });
  assert.ok(channel);
  // Baseline at x=30 is y=30; parallel is shifted by -10.
  assert.deepEqual(channel.parallel, [{ x: 0, y: -10 }, { x: 10, y: 0 }]);
});

test("a vertical baseline shifts horizontally and invalid input fails closed", () => {
  const channel = parallelChannelScreenGeometry({ x: 50, y: 10 }, { x: 50, y: 90 }, { x: 80, y: 40 });
  assert.ok(channel);
  assert.deepEqual(channel.parallel, [{ x: 80, y: 10 }, { x: 80, y: 90 }]);
  assert.equal(parallelChannelScreenGeometry({ x: Number.NaN, y: 0 }, { x: 1, y: 1 }, { x: 2, y: 2 }), null);
  assert.equal(parallelChannelScreenGeometry(null, { x: 1, y: 1 }, { x: 2, y: 2 }), null);
});

test("arrowhead points along the segment, scales with width and never exceeds the shaft", () => {
  const head = arrowHeadScreenGeometry({ x: 0, y: 0 }, { x: 100, y: 0 }, 2);
  assert.ok(head);
  assert.deepEqual(head.tip, { x: 100, y: 0 });
  assert.equal(arrowHeadLengthCssPx(2), 10);
  assert.deepEqual(head.left, { x: 90, y: 5 });
  assert.deepEqual(head.right, { x: 90, y: -5 });
  assert.ok(head.shaftEnd.x < 100 && head.shaftEnd.x > 90, "shaft stops inside the head");
  assert.equal(arrowHeadLengthCssPx(6), 24);
  const short = arrowHeadScreenGeometry({ x: 0, y: 0 }, { x: 4, y: 0 }, 6);
  assert.ok(short);
  assert.equal(short.left.x, 0, "head is clamped to the segment length");
  assert.equal(arrowHeadScreenGeometry({ x: 3, y: 3 }, { x: 3, y: 3 }, 2), null);
});

test("polygon containment uses even-odd ray casting", () => {
  const square = [{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 10 }, { x: 0, y: 10 }];
  assert.equal(pointInScreenPolygon(5, 5, square), true);
  assert.equal(pointInScreenPolygon(15, 5, square), false);
  const parallelogram = [{ x: 0, y: 10 }, { x: 10, y: 0 }, { x: 10, y: 5 }, { x: 0, y: 15 }];
  assert.equal(pointInScreenPolygon(5, 9, parallelogram), true);
  assert.equal(pointInScreenPolygon(5, 2, parallelogram), false);
  assert.equal(pointInScreenPolygon(5, 5, square.slice(0, 2)), false);
});
