import type { KeyboardEvent } from "react";
import { isContextMenuKey } from "../ui/helpers.js";

/**
 * The keyboard way to what a right-click on a drawing tool opens (its variants, or its settings):
 * → (the toolbar is vertical and the menu opens to its right), Shift+F10 or the menu key. The
 * tool's own context-menu handler runs, so pointer and keyboard open the same thing.
 */
export function openToolMenuFromKeyboard(event: KeyboardEvent<HTMLButtonElement>): void {
  if (event.key !== "ArrowRight" && !isContextMenuKey(event)) return;
  event.preventDefault();
  event.currentTarget.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
}
