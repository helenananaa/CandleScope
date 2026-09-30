import type { DrawingToolId, SavedDrawing } from "./drawingTypes.js";

/** Keep the exact variant when entering an existing object's editing tool. */
export function drawingToolForSavedObject(drawing: SavedDrawing): DrawingToolId {
  switch (drawing.type) {
    case "line": return drawing.lineType ?? "line-segment";
    case "axis-line": return `line-${drawing.axisLineType ?? "horizontal"}`;
    case "angle-measure": return "angle-measure";
    case "shape": return `shape-${drawing.shapeType ?? "rectangle"}`;
    case "position": return `position-${drawing.direction ?? "long"}`;
    case "freehand": return "pen";
    default: return drawing.type;
  }
}

/** A manually chosen creation tool must never inherit automatic edit exit behavior. */
export function isAutomaticObjectEditing(activeTool: DrawingToolId | null, automaticTool: DrawingToolId | null): boolean {
  return automaticTool !== null && activeTool === automaticTool;
}

// Native panes share one chart container and transfer the tool on hover. Keep
// this UI-only intent with that container so a blank click in another pane
// cannot turn automatic editing into drawing creation. Nothing is persisted.
const automaticTools = new WeakMap<object, DrawingToolId>();
export function rememberAutomaticObjectTool(surface: object | null | undefined, tool: DrawingToolId): void {
  if (surface) automaticTools.set(surface, tool);
}
export function automaticObjectTool(surface: object | null | undefined): DrawingToolId | null {
  return surface ? automaticTools.get(surface) ?? null : null;
}
export function clearAutomaticObjectTool(surface: object | null | undefined): void {
  if (surface) automaticTools.delete(surface);
}
