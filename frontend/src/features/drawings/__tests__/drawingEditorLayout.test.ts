import assert from "node:assert/strict";
import test from "node:test";
import { clampEditorPosition, placeEditorPopover } from "../drawingEditorLayout.js";

test("drag positions stay inside a chart and recover when its container shrinks", () => {
  assert.deepEqual(clampEditorPosition({ x: -100, y: 900 }, { width: 300, height: 44 }, { width: 800, height: 400 }), { x: 8, y: 348 });
  assert.deepEqual(clampEditorPosition({ x: 492, y: 348 }, { width: 300, height: 44 }, { width: 340, height: 160 }), { x: 32, y: 108 });
  assert.deepEqual(clampEditorPosition({ x: 200, y: 200 }, { width: 300, height: 44 }, { width: 200, height: 30 }), { x: 0, y: 0 });
});

test("popovers flip above bottom-edge triggers and fit narrow viewports", () => {
  assert.deepEqual(placeEditorPopover({ left: 700, top: 650, width: 32, height: 32 }, { width: 236, height: 220 }, { width: 1280, height: 720 }), { x: 496, y: 422 });
  const point = placeEditorPopover({ left: 0, top: 20, width: 32, height: 32 }, { width: 304, height: 464 }, { width: 320, height: 480 });
  assert.deepEqual(point, { x: 8, y: 8 });
});
