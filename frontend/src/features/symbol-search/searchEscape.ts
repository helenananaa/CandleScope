/** Capture Escape while search is open, including focus lost to the page body. */
export function listenForSearchEscape(target: EventTarget, dismissTopLayer: () => void): () => void {
  const handleKeyDown = (event: Event) => {
    if ((event as KeyboardEvent).key !== "Escape" || event.defaultPrevented) return;
    event.preventDefault();
    event.stopPropagation();
    dismissTopLayer();
  };
  target.addEventListener("keydown", handleKeyDown, { capture: true });
  return () => target.removeEventListener("keydown", handleKeyDown, { capture: true });
}
