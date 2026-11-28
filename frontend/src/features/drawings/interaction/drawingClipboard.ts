import { exportDrawingDocument, drawingIdPrefix } from "../core/drawingCodec.js";
import type { DrawingDocument } from "../core/drawingDocument.js";
import { nextDrawingGroupId } from "../drawingGroups.js";
import { nextDrawingId } from "../drawingModel.js";
import { normalizeSavedDrawingItemStrict } from "../drawingPersistence.js";
import type { SavedDrawing } from "../drawingTypes.js";
import { MAX_DRAWING_SELECTION, type DrawingSelection } from "./drawingMultiSelection.js";

/**
 * Copy and paste of drawings (PL-4). The clipboard lives in memory for this
 * window only and holds detached copies; nothing is stored beside the
 * canonical document. Pasting creates new drawings with new ids and new
 * group ids, so a copy never shares identity with its original.
 */
export interface DrawingClipboardContents {
  readonly sourceScope: string;
  readonly drawings: readonly SavedDrawing[];
}

let contents: DrawingClipboardContents | null = null;

export function copyDrawingSelection(document: DrawingDocument, selection: DrawingSelection): number {
  const all = exportDrawingDocument(document);
  if (!all) return 0;
  const wanted = new Set(selection.ids);
  const drawings = all.filter((drawing) => drawing.id !== undefined && wanted.has(drawing.id)).slice(0, MAX_DRAWING_SELECTION);
  if (drawings.length === 0) return 0;
  contents = Object.freeze({ sourceScope: document.scopeKey, drawings: Object.freeze(drawings) });
  return drawings.length;
}

export function readDrawingClipboard(): DrawingClipboardContents | null {
  return contents;
}

export function clearDrawingClipboard(): void {
  contents = null;
}

/**
 * Detached copies ready to create. `place` moves each copy (for example a
 * small offset on the source chart); returning null drops the whole paste.
 * Copies are unlocked so they can be placed, and keep every other property.
 */
export function pastedDrawings(
  source: DrawingClipboardContents,
  place: (drawing: SavedDrawing) => SavedDrawing | null,
): readonly SavedDrawing[] | null {
  const groups = new Map<string, string>();
  const created: SavedDrawing[] = [];
  for (const original of source.drawings) {
    const { id: _id, locked: _locked, groupId, ...rest } = original;
    const moved = place(rest as SavedDrawing);
    if (!moved) return null;
    let nextGroup: string | undefined;
    if (groupId) {
      nextGroup = groups.get(groupId) ?? nextDrawingGroupId();
      groups.set(groupId, nextGroup);
    }
    const candidate = normalizeSavedDrawingItemStrict({
      ...moved,
      id: nextDrawingId(drawingIdPrefix(original.type)),
      ...(nextGroup ? { groupId: nextGroup } : {}),
    });
    if (!candidate?.id) return null;
    created.push(candidate);
  }
  return Object.freeze(created);
}
