import type { DrawingDocument } from "./core/drawingDocument.js";
import type { DrawingStylePatch } from "./drawingInteractionController.js";

export interface DrawingObjectApi {
  getObjectDocument(): DrawingDocument;
  subscribeObjectDocument(listener: () => void): () => void;
  selectObject(id: string): boolean;
  updateObject(id: string, patch: DrawingStylePatch): boolean;
  deleteObject(id: string): boolean;
  reorderObject(id: string, placement: "front" | "back"): boolean;
}

/** Canonical z-order is back to front; preserve every other entity's order. */
export function drawingObjectOrder(document: DrawingDocument, id: string, placement: "front" | "back"): readonly string[] | null {
  if (!document.entities.has(id) || !document.zOrder.includes(id)) return null;
  if ((placement === "front" ? document.zOrder.at(-1) : document.zOrder[0]) === id) return document.zOrder;
  const rest = document.zOrder.filter(candidate => candidate !== id);
  return placement === "front" ? [...rest, id] : [id, ...rest];
}
