type SearchKey = Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "altKey" | "isComposing" | "defaultPrevented" | "repeat" | "keyCode">;

export function quickSearchCharacter(event: SearchKey, blocked: boolean): string | null {
  if (blocked || event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey
    || event.isComposing || event.keyCode === 229 || event.repeat) return null;
  return /^[a-z0-9]$/i.test(event.key) ? event.key : null;
}

export function searchKeyboardBlocked(document: Document, event: KeyboardEvent): boolean {
  const editing = "input, textarea, select, [contenteditable]:not([contenteditable=false]), [role=textbox], [role=combobox], [role=spinbutton], .monaco-editor";
  if (document.activeElement?.closest(editing)) return true;
  if (event.composedPath().some((target) => target instanceof Element && target.closest(editing))) return true;
  return Array.from(document.querySelectorAll<HTMLElement>(
    '[role="dialog"], [aria-modal="true"], dialog[open], [class*="modal-overlay"], .st-overlay, .dw-overlay, .workspace-panel-overlay, .replay-launcher-overlay',
  )).some((element) => element.getClientRects().length > 0 && getComputedStyle(element).visibility !== "hidden");
}
