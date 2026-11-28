import type { DrawingCommand } from "../core/drawingCommands.js";
import type { DrawingDocument } from "../core/drawingDocument.js";
import { nextDrawingGroupId } from "../drawingGroups.js";
import { drawingVisibleAtInterval } from "../drawingVisibility.js";

/**
 * Multi-selection and groups (PL-4), as pure functions over the canonical
 * document. The primary id is the drawing whose style bar shows; `ids` keeps
 * document z-order and always contains the primary.
 */
export interface DrawingSelection {
  readonly primary: string | null;
  readonly ids: readonly string[];
}

export const EMPTY_DRAWING_SELECTION: DrawingSelection = Object.freeze({ primary: null, ids: Object.freeze([]) });

/** Upper bound for one selection, copy or group: the saved-drawing limit. */
export const MAX_DRAWING_SELECTION = 500;

function inZOrder(document: DrawingDocument, ids: Iterable<string>): string[] {
  const wanted = new Set(ids);
  return document.zOrder.filter((id) => wanted.has(id)).slice(0, MAX_DRAWING_SELECTION);
}

export function drawingSelection(document: DrawingDocument, primary: string | null, ids: Iterable<string>): DrawingSelection {
  const ordered = inZOrder(document, primary === null ? ids : [...ids, primary]);
  const nextPrimary = primary !== null && ordered.includes(primary) ? primary : ordered.at(-1) ?? null;
  return Object.freeze({ primary: nextPrimary, ids: Object.freeze(ordered) });
}

/** The drawing and every other member of its group, in z-order. */
export function groupMemberIds(document: DrawingDocument, id: string): readonly string[] {
  const groupId = document.entities.get(id)?.style.groupId;
  if (!groupId) return document.entities.has(id) ? [id] : [];
  return inZOrder(document, [...document.entities.values()]
    .filter((entity) => entity.style.groupId === groupId)
    .map((entity) => entity.id));
}

/**
 * Selection after clicking a drawing. Shift toggles the drawing (with its
 * group). A plain click on a member of a multi-selection keeps it so the
 * members can be dragged together; any other click selects the drawing and
 * its group.
 */
export function selectionAfterClick(
  document: DrawingDocument,
  current: DrawingSelection,
  hitId: string,
  toggle: boolean,
): DrawingSelection {
  const members = groupMemberIds(document, hitId);
  if (members.length === 0) return current;
  if (toggle) {
    const selected = new Set(current.ids);
    if (selected.has(hitId)) {
      for (const id of members) selected.delete(id);
      const primary = current.primary !== null && selected.has(current.primary) ? current.primary : null;
      return drawingSelection(document, primary, selected);
    }
    for (const id of members) selected.add(id);
    return drawingSelection(document, hitId, selected);
  }
  if (current.ids.length > 1 && current.ids.includes(hitId)) return drawingSelection(document, hitId, current.ids);
  return drawingSelection(document, hitId, members);
}

/** Every drawing a user can see on this interval. */
export function selectAllDrawings(document: DrawingDocument, interval: string): DrawingSelection {
  const ids = document.zOrder.filter((id) => {
    const style = document.entities.get(id)?.style;
    return !!style && style.hidden !== true && drawingVisibleAtInterval(style, interval);
  });
  return drawingSelection(document, ids.at(-1) ?? null, ids);
}

/** One undoable batch that puts every selected drawing in a new group. */
export function groupSelectionCommands(
  document: DrawingDocument,
  selection: DrawingSelection,
  groupId = nextDrawingGroupId(),
): readonly DrawingCommand[] | null {
  const ids = selection.ids.filter((id) => document.entities.has(id));
  if (ids.length < 2) return null;
  return Object.freeze(ids.map((id) => Object.freeze({ type: "update-style" as const, id, patch: Object.freeze({ groupId }) })));
}

/** One undoable batch that removes the selected drawings from their groups. */
export function ungroupSelectionCommands(document: DrawingDocument, selection: DrawingSelection): readonly DrawingCommand[] | null {
  const ids = selection.ids.filter((id) => document.entities.get(id)?.style.groupId !== undefined);
  if (ids.length === 0) return null;
  return Object.freeze(ids.map((id) => Object.freeze({ type: "update-style" as const, id, patch: Object.freeze({ groupId: undefined }) })));
}

export function deleteSelectionCommands(document: DrawingDocument, selection: DrawingSelection): readonly DrawingCommand[] | null {
  const ids = selection.ids.filter((id) => document.entities.has(id));
  return ids.length === 0 ? null : Object.freeze(ids.map((id) => Object.freeze({ type: "delete" as const, id })));
}

export function selectionIsGrouped(document: DrawingDocument, selection: DrawingSelection): boolean {
  return selection.ids.some((id) => document.entities.get(id)?.style.groupId !== undefined);
}
