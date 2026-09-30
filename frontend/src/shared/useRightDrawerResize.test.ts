import assert from "node:assert/strict";
import test from "node:test";
import { marketRailWidthBounds } from "./marketRailLayout.js";

import {
  clampRightDrawerWidth,
  rightDrawerWidthBounds,
  type RightDrawerResizeOptions,
} from "./useRightDrawerResize.js";

const options: RightDrawerResizeOptions = {
  initialWidth: 430,
  minWidth: 360,
  maxWidth: 780,
  viewportMargin: 80,
};

test("right drawer width stays inside its content and viewport bounds", () => {
  assert.deepEqual(rightDrawerWidthBounds(options, 1440), { min: 360, max: 780 });
  assert.equal(clampRightDrawerWidth(200, options, 1440), 360);
  assert.equal(clampRightDrawerWidth(600, options, 1440), 600);
  assert.equal(clampRightDrawerWidth(1000, options, 1440), 780);
});

test("right drawer can contract below its normal minimum on a narrow viewport", () => {
  assert.deepEqual(rightDrawerWidthBounds(options, 320), { min: 240, max: 240 });
  assert.equal(clampRightDrawerWidth(430, options, 320), 240);
});

test("uncapped drawers can reach the left edge at any viewport size", () => {
  const fullscreenOptions = { initialWidth: 430, minWidth: 360 };
  for (const viewport of [320, 1440, 3840]) {
    assert.equal(clampRightDrawerWidth(9999, fullscreenOptions, viewport), viewport);
    assert.equal(rightDrawerWidthBounds(fullscreenOptions, viewport).max, viewport);
  }
});

test("market rail can occupy most of the window while preserving a chart strip", () => {
  assert.deepEqual(marketRailWidthBounds(1440), { min: 260, max: 1275 });
  assert.deepEqual(marketRailWidthBounds(320), { min: 155, max: 155 });
  assert.deepEqual(marketRailWidthBounds(100), { min: 0, max: 0 });
});
