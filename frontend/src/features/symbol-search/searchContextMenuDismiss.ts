/** Close only for interaction that invalidates the search menu's own anchor. */
export function listenForSearchContextMenuDismiss(
  windowTarget: EventTarget,
  modalTarget: EventTarget | null,
  dismiss: () => void,
): () => void {
  windowTarget.addEventListener("click", dismiss);
  windowTarget.addEventListener("contextmenu", dismiss);
  windowTarget.addEventListener("resize", dismiss);
  // Live order-book centering also emits scroll events. Those occur behind the
  // modal and must not close the menu before the user can choose a watchlist.
  modalTarget?.addEventListener("scroll", dismiss, { capture: true });
  return () => {
    windowTarget.removeEventListener("click", dismiss);
    windowTarget.removeEventListener("contextmenu", dismiss);
    windowTarget.removeEventListener("resize", dismiss);
    modalTarget?.removeEventListener("scroll", dismiss, { capture: true });
  };
}
