import type { ChartSurfaceActions } from "../../chart-adapter/useChartSurfaceRuntime.js";
import type { DrawingRuntime } from "../drawings/useDrawingRuntime.js";
import type { DrawingCommand } from "../drawings/core/drawingCommands.js";
import { command, type ControlCommandGroup } from "./commandRegistry.js";
import { array, bool, choice, empty, nullable, number, object, optional, record, schema, text } from "./commandSchema.js";

const batchShapes = {
  create: object({ type: choice(["create"]), entity: record, at: optional(number(0, 512, true)) }),
  move: object({ type: choice(["move", "resize"]), id: text(128), geometry: record }),
  style: object({ type: choice(["update-style"]), id: text(128), patch: record }),
  delete: object({ type: choice(["delete"]), id: text(128) }),
  clear: object({ type: choice(["clear"]) }),
  reorder: object({ type: choice(["reorder"]), order: array(text(128), 512) }),
};
const commandBatch = schema<DrawingCommand[]>({ type: "array", minItems: 1, maxItems: 128,
  items: { oneOf: Object.values(batchShapes).map((shape) => shape.jsonSchema) },
  description: "Atomic DrawingCommand batch. entity={id,kind,geometry,style}; kind is line/axis-line/angle-measure/text/fibonacci/position/shape/freehand/highlighter. geometry/style.kind must match kind. Line example: geometry={kind:'line',lineType:'line-segment',dataPoints:[{time:UNIX_SECONDS,price:NUMBER},{time:UNIX_SECONDS,price:NUMBER}]},style={kind:'line',color:'#ffcc00',lineWidth:2}. Read inspect.entities for other existing object shapes. The canonical engine validates all fields and the full batch before commit." }, (v) => {
  const items = array(record, 128).parse(v);
  if (!items.length) throw new Error("EMPTY_DRAWING_BATCH");
  return items.map((item) => {
    switch (item.type) {
      case "create": return batchShapes.create.parse(item);
      case "move": case "resize": return batchShapes.move.parse(item);
      case "update-style": return batchShapes.style.parse(item);
      case "delete": return batchShapes.delete.parse(item);
      case "clear": return batchShapes.clear.parse(item);
      case "reorder": return batchShapes.reorder.parse(item);
      default: throw new Error("INVALID_DRAWING_COMMAND");
    }
  }) as DrawingCommand[];
});
export function drawingCommands(cellId: string, surface: { actions: ChartSurfaceActions }, runtime: DrawingRuntime, sessionIdentity: string, writable = true): ControlCommandGroup {
  const panes = () => [...surface.actions.getDrawingPaneApis()].filter(([, api]) => api.objects && api.control);
  const ready = () => panes().some(([, api]) => api.control!.isReady());
  const api = (paneId: string) => {
    const selected = surface.actions.getDrawingPaneApis().get(paneId);
    if (!selected?.control || !selected.objects) throw new Error("DRAWING_PANE_UNAVAILABLE"); return selected;
  };
  const pane = object({ paneId: text(128) });
  const group: ControlCommandGroup = { id: `drawings:${cellId}`, title: `Chart ${cellId}: canonical drawing objects and tools`,
    context: () => ({ sessionIdentity, preferences: runtime.view, panes: panes().map(([paneId, item]) => ({ paneId, ready: item.control!.isReady(), scope: item.objects!.getObjectDocument().scopeKey, revision: item.objects!.getObjectDocument().documentRevision })) }),
    snapshot: () => ({ preferences: runtime.view, panes: panes().map(([paneId, item]) => {
      const doc = item.objects!.getObjectDocument(); return { paneId, ready: item.control!.isReady(), readiness: item.control!.readiness(), scopeKey: doc.scopeKey, revision: doc.documentRevision, entities: [...doc.entities.values()], zOrder: doc.zOrder };
    }) }), commands: [
      command("prepare", "Request the same drawing scope recovery as the UI mutation barrier, without editing a document. Inspect pane.ready before submitting a new edit.", pane,
        ({ paneId }) => ({ ready: api(paneId).control!.prepare() }), { available: () => panes().length > 0 }),
      command("apply", "Apply an atomic drawing document batch with scope and revision guards. Uses existing persistence, renderer publication and undo history. An applied result does not claim disk flush.",
        object({ paneId: text(128), scopeKey: text(512), expectedRevision: number(0, 1e15, true), commands: commandBatch }),
        ({ paneId, scopeKey, expectedRevision, commands }) => api(paneId).control!.applyCommands(commands, scopeKey, expectedRevision), { available: ready }),
      command("select", "Select a visible drawing object by ID.", object({ paneId: text(128), objectId: text(128) }), ({ paneId, objectId }) => {
        if (!api(paneId).objects!.selectObject(objectId)) throw new Error("DRAWING_SELECTION_REJECTED");
      }, { available: ready }),
      command("undo", "Undo a drawing edit using the existing drawing history.", pane, ({ paneId }) => { if (!api(paneId).control!.history("undo")) throw new Error("DRAWING_UNDO_UNAVAILABLE"); }, { available: ready }),
      command("redo", "Redo a drawing edit.", pane, ({ paneId }) => { if (!api(paneId).control!.history("redo")) throw new Error("DRAWING_REDO_UNAVAILABLE"); }, { available: ready }),
      command("visibility", "Show/hide drawings without changing object data.", object({ hidden: bool }), ({ hidden }) => runtime.actions.setDrawingsHidden(hidden)),
      command("tool", "Choose a native drawing/cursor tool.", object({ tool: choice(["cursor-default", "cursor-crosshair", "cursor-dot", "cursor-highlighter", "cursor-plain", "eraser", "line-segment", "line-ray", "line-infinite", "line-horizontal", "line-vertical", "line-cross", "angle-measure", "fibonacci", "position-long", "position-short", "shape-rectangle", "shape-ellipse", "text", "pen", "highlighter"]) }), ({ tool }) => runtime.actions.setDrawingTool(tool)),
      command("preferences", "Set drawing tool preferences through UI actions.", object({ color: optional(text(64)), size: optional(number(1, 100)), fontSize: optional(number(6, 256)), bold: optional(bool), italic: optional(bool), snap: optional(bool), continuous: optional(bool), autoSelect: optional(bool), positionSize: optional(number(0.000001)) }),
        ({ color, size, fontSize, bold, italic, snap, continuous, autoSelect, positionSize }) => {
          const a = runtime.actions; if (color !== undefined) a.setPenColor(color); if (size !== undefined) a.setPenSize(size);
          if (fontSize !== undefined) a.setTextFontSize(fontSize); if (bold !== undefined) a.setTextBold(bold); if (italic !== undefined) a.setTextItalic(italic);
          if (snap !== undefined) a.handleDrawingSnapEnabledChange(snap); if (continuous !== undefined) a.handleDrawingContinuousEnabledChange(continuous);
          if (autoSelect !== undefined) a.handleDrawingAutoSelectEnabledChange(autoSelect); if (positionSize !== undefined) a.handlePositionSizeChange(positionSize);
        }),
      command("clear", "Clear all drawing panes through the existing UI action.", empty, () => runtime.actions.handleClearDrawing(), { available: ready }),
      command("fibonacci", "Set Fibonacci default levels/inversion through the native preference actions.", object({ levels: optional(nullable(array(object({ level: number(-1000, 1000), color: text(64), enabled: bool }), 64))), inverted: optional(bool) }), ({ levels, inverted }) => {
        if (levels !== undefined) runtime.actions.handleFibLevelsChange(levels); if (inverted !== undefined) runtime.actions.handleFibInvertedChange(inverted);
      }),
    ] };
  if (!writable) group.commands = group.commands.map((item) => ({ ...item, available: () => false }));
  return group;
}
