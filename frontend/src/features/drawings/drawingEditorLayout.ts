export interface EditorPoint { x: number; y: number }
export interface EditorSize { width: number; height: number }
export interface EditorRect extends EditorSize { left: number; top: number }

export function clampEditorPosition(point: EditorPoint, size: EditorSize, bounds: EditorSize, inset = 8): EditorPoint {
  const left = Math.min(inset, Math.max(0, bounds.width - size.width));
  const top = Math.min(inset, Math.max(0, bounds.height - size.height));
  return {
    x: Math.max(left, Math.min(point.x, bounds.width - size.width - inset)),
    y: Math.max(top, Math.min(point.y, bounds.height - size.height - inset)),
  };
}

/** Prefer below the anchor, flip above when possible, otherwise fit the viewport. */
export function placeEditorPopover(anchor: EditorRect, size: EditorSize, viewport: EditorSize): EditorPoint {
  const below = anchor.top + anchor.height + 8;
  const above = anchor.top - size.height - 8;
  return clampEditorPosition({
    x: anchor.left + anchor.width - size.width,
    y: below + size.height <= viewport.height - 8 ? below : above >= 8 ? above : below,
  }, size, viewport);
}
