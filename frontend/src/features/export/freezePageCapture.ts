import { t } from "../../i18n/index.js";

/** Copy the page synchronously, before live data can replace any source pixels. */
export function freezePageCapture(
  source: HTMLElement,
  include: (element: HTMLElement) => boolean,
): HTMLElement {
  const copy = (node: Node): Node | null => {
    if (!(node instanceof Element)) return node.cloneNode(false);
    if (!include(node as HTMLElement)) return null;
    const clone = node.cloneNode(false) as HTMLElement;
    const style = window.getComputedStyle(node);
    for (const property of Array.from(style)) {
      clone.style.setProperty(property, style.getPropertyValue(property));
    }
    // A cloned live canvas is blank. Copy its bitmap in this same JS turn;
    // html-to-image can then rasterize the detached copy at its own pace.
    if (node instanceof HTMLCanvasElement) {
      const canvas = clone as HTMLCanvasElement;
      const context = canvas.getContext("2d");
      if (!context) throw new Error(t("export.fallbackCanvasFailed"));
      if (node.width && node.height) context.drawImage(node, 0, 0);
    }
    if (node instanceof HTMLInputElement) {
      (clone as HTMLInputElement).value = node.value;
      (clone as HTMLInputElement).checked = node.checked;
    }
    if (node instanceof HTMLTextAreaElement) {
      clone.textContent = node.value;
      return clone;
    }
    for (const child of Array.from(node.childNodes)) {
      const childCopy = copy(child);
      if (childCopy) clone.appendChild(childCopy);
    }
    if (node instanceof HTMLSelectElement) {
      (clone as HTMLSelectElement).value = node.value;
    }
    return clone;
  };
  return copy(source) as HTMLElement;
}
