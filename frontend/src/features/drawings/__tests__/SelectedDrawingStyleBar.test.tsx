import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { getLocale, setLocale } from "../../../i18n/index.js";
import SelectedDrawingStyleBar from "../SelectedDrawingStyleBar.js";
import { selectedDrawingMetaFromSavedDrawing } from "../drawingSelectionController.js";
import { importSavedDrawings } from "../core/drawingCodec.js";
import { applyDrawingCommands } from "../core/drawingCommands.js";
import { drawingCommandsForSavedDrawing } from "../core/drawingDocumentRuntime.js";

test("selected drawing bar shows the selected object's own style and controls", () => {
  const previousLocale = getLocale();
  try {
    setLocale("zh-CN");
    const shape = selectedDrawingMetaFromSavedDrawing({
      id: "shape-one",
      type: "shape",
      shapeType: "rectangle",
      color: "#123456",
      lineWidth: 4,
      fillColor: "#abcdef",
      fillOpacity: 0.4,
      lineStyle: "dashed",
    });
    assert.ok(shape);
    const html = renderToStaticMarkup(<SelectedDrawingStyleBar
      drawing={shape}
      onPatch={() => {}}
      onDelete={() => {}}
    />);
    assert.match(html, /data-selected-drawing-id="shape-one"/);
    assert.match(html, /value="#123456"/);
    assert.match(html, /value="4"/);
    assert.match(html, /更多画图设置/);
    assert.match(html, /aria-expanded="false"/);
    assert.doesNotMatch(html, /value="#abcdef"/);
    const expandedHtml = renderToStaticMarkup(<SelectedDrawingStyleBar
      drawing={shape}
      openRequestRevision={1}
      onPatch={() => {}}
      onDelete={() => {}}
    />);
    assert.match(expandedHtml, /value="#abcdef"/);
    assert.match(expandedHtml, /填充颜色/);
    assert.match(expandedHtml, /aria-label="虚线" aria-pressed="true"/);
    assert.match(expandedHtml, /role="dialog"/);
    assert.match(expandedHtml, /保存并关闭/);
    assert.match(expandedHtml, /取消/);
  } finally {
    setLocale(previousLocale);
  }
});

test("selection snapshots expose per-object settings including position and fib levels", () => {
  const position = selectedDrawingMetaFromSavedDrawing({
    id: "position-one", type: "position", positionSize: 5200,
  });
  assert.equal(position?.positionSize, 5200);
  const fib = selectedDrawingMetaFromSavedDrawing({
    id: "fib-one", type: "fibonacci", levels: [
      { level: 0.5, color: "#123456", enabled: true },
    ],
  });
  assert.deepEqual(fib?.levels, [{ level: 0.5, color: "#123456", enabled: true }]);
});

test("selected shape settings persist through a style-only document revision", () => {
  const shape = {
    id: "shape-one",
    type: "shape" as const,
    shapeType: "rectangle" as const,
    dataPoints: [{ time: 100, price: 10 }, { time: 200, price: 20 }],
    color: "#123456",
    lineWidth: 2,
    fillColor: "#abcdef",
    fillOpacity: 0.25,
    lineStyle: "solid" as const,
  };
  const document = importSavedDrawings("test-scope", [shape]);
  assert.ok(document);
  const commands = drawingCommandsForSavedDrawing({
    ...shape, fillOpacity: 0.5, lineStyle: "dotted",
  }, { type: "update-style" });
  assert.ok(commands);
  const result = applyDrawingCommands(document, commands);
  assert.equal(result.ok, true);
  const entity = result.document.entities.get(shape.id);
  assert.ok(entity);
  assert.equal(entity.geometryRevision, 1);
  assert.equal(entity.styleRevision, 2);
  assert.equal(entity.style.kind, "shape");
  if (entity.style.kind === "shape") {
    assert.equal(entity.style.fillOpacity, 0.5);
    assert.equal(entity.style.lineStyle, "dotted");
  }
});
