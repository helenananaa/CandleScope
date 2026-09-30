import assert from "node:assert/strict";
import test from "node:test";
import { drawingToolForSavedObject, isAutomaticObjectEditing, rememberAutomaticObjectTool, automaticObjectTool, clearAutomaticObjectTool } from "../drawingAutoSelection.js";
import type { DrawingToolId, SavedDrawing } from "../drawingTypes.js";

test("automatic selection preserves every drawing family and variant", () => {
  const examples: [SavedDrawing, DrawingToolId][] = [
    [{ type: "line", lineType: "line-ray" }, "line-ray"],
    [{ type: "line", lineType: "line-infinite" }, "line-infinite"],
    [{ type: "line" }, "line-segment"],
    [{ type: "axis-line", axisLineType: "vertical" }, "line-vertical"],
    [{ type: "axis-line", axisLineType: "cross" }, "line-cross"],
    [{ type: "axis-line" }, "line-horizontal"],
    [{ type: "angle-measure" }, "angle-measure"],
    [{ type: "shape", shapeType: "ellipse" }, "shape-ellipse"],
    [{ type: "shape" }, "shape-rectangle"],
    [{ type: "position", direction: "short" }, "position-short"],
    [{ type: "position" }, "position-long"],
    [{ type: "text" }, "text"],
    [{ type: "fibonacci" }, "fibonacci"],
    [{ type: "freehand", dataPoints: [] }, "pen"],
    [{ type: "highlighter", dataPoints: [] }, "highlighter"],
  ];
  for (const [drawing, expected] of examples) assert.equal(drawingToolForSavedObject(drawing), expected);
});

test("automatic editing exit is limited to its recorded tool, including explicit object-list entry", () => {
  assert.equal(isAutomaticObjectEditing("shape-rectangle", "shape-rectangle"), true);
  assert.equal(isAutomaticObjectEditing("text", "text"), true);
  assert.equal(isAutomaticObjectEditing("pen", "pen"), true);
  assert.equal(isAutomaticObjectEditing("shape-rectangle", null), false);
  assert.equal(isAutomaticObjectEditing("line-ray", "shape-rectangle"), false);
  assert.equal(isAutomaticObjectEditing("cursor-default", "shape-rectangle"), false);
  assert.equal(isAutomaticObjectEditing(null, null), false);
});


test("automatic editing survives native pane ownership transfer and stays isolated between charts", () => {
  const chart = {}, otherChart = {};
  rememberAutomaticObjectTool(chart, "shape-rectangle");
  assert.equal(isAutomaticObjectEditing(null, automaticObjectTool(chart)), false);
  assert.equal(isAutomaticObjectEditing("shape-rectangle", automaticObjectTool(chart)), true);
  assert.equal(automaticObjectTool(otherChart), null);
  rememberAutomaticObjectTool(chart, "text");
  assert.equal(automaticObjectTool(chart), "text");
  clearAutomaticObjectTool(chart);
  assert.equal(automaticObjectTool(chart), null);
});
