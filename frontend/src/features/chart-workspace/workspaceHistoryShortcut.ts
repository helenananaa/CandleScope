/** Only call from the workspace panel's key handler, never a global listener. */
export function workspaceHistoryShortcut(
  event: Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "altKey" | "shiftKey" | "defaultPrevented">,
  state: { enabled: boolean; editable: boolean; canUndo: boolean; canRedo: boolean },
): "undo" | "redo" | null {
  if (!state.enabled || state.editable || event.defaultPrevented
    || (!event.ctrlKey && !event.metaKey) || event.altKey) return null;
  const key = event.key.toLowerCase();
  if (key === "z" && !event.shiftKey) return state.canUndo ? "undo" : null;
  if ((key === "z" && event.shiftKey) || (key === "y" && !event.shiftKey)) {
    return state.canRedo ? "redo" : null;
  }
  return null;
}
