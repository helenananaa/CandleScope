// DOM side of the overlay stack: the host element, Escape, inert background, focus.
import { useEffect, useId, useLayoutEffect, useRef, useSyncExternalStore, type RefObject } from "react";
import { createOverlayStack, type DrawerSide, type OverlayKind } from "./overlayStack.js";

export const overlayStack = createOverlayStack();

let host: HTMLElement | null = null;

/** Container for overlays, outside the app root so a modal can make the app inert. */
export function overlayHost(): HTMLElement {
  if (host && host.isConnected) return host;
  host = document.createElement("div");
  host.className = "ui-overlay-root";
  host.dataset.overlayRoot = "true";
  document.body.append(host);
  return host;
}

const layerElements = new Map<string, HTMLElement>();

function syncInert() {
  const root = document.getElementById("root");
  if (root) root.inert = overlayStack.hasModal();
  for (const [id, element] of layerElements) element.inert = overlayStack.inert(id);
}

let installed = false;
function install() {
  if (installed || typeof document === "undefined") return;
  installed = true;
  // Capture phase: the topmost managed layer closes before any older Escape handler runs.
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || event.defaultPrevented || event.isComposing) return;
    if (overlayStack.escape()) {
      event.preventDefault();
      event.stopPropagation();
    }
  }, true);
  overlayStack.subscribe(syncInert);
}

const FOCUSABLE = [
  "a[href]", "button:not([disabled])", "input:not([disabled]):not([type='hidden'])", "select:not([disabled])",
  "textarea:not([disabled])", "[tabindex]:not([tabindex='-1'])", "[contenteditable='true']",
].join(",");

export function focusableWithin(element: HTMLElement): HTMLElement[] {
  return [...element.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => !el.closest("[inert]") && el.getClientRects().length > 0);
}

/** Next element for Tab / Shift+Tab inside a trap, wrapping at the ends. */
export function trappedFocusTarget(items: readonly HTMLElement[], active: Element | null, backwards: boolean): HTMLElement | null {
  if (!items.length) return null;
  const index = active ? items.indexOf(active as HTMLElement) : -1;
  if (backwards) return index <= 0 ? items[items.length - 1] ?? null : null;
  return index === -1 || index === items.length - 1 ? items[0] ?? null : null;
}

export interface OverlayLayerOptions {
  open: boolean;
  kind: OverlayKind;
  side?: DrawerSide;
  onClose: () => void;
  closeOnEscape?: boolean;
  /** The layer's root element; it receives the z-index and inert state. */
  layerRef: RefObject<HTMLElement | null>;
  /** Element focused on open; defaults to the first focusable element, then the layer. */
  initialFocusRef?: RefObject<HTMLElement | null>;
  /** Element whose focusables Tab cycles through (modals). */
  trapRef?: RefObject<HTMLElement | null>;
  /** Element focused on close; defaults to whatever had focus on open. */
  returnFocusRef?: RefObject<HTMLElement | null>;
}

/** Registers a layer while open and returns its z-index. */
export function useOverlayLayer({ open, kind, side, onClose, closeOnEscape = true, layerRef, initialFocusRef, trapRef, returnFocusRef }: OverlayLayerOptions): number | undefined {
  const id = useId();
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const zIndex = useSyncExternalStore(overlayStack.subscribe, () => overlayStack.zIndex(id), () => undefined);

  useLayoutEffect(() => {
    if (!open) return undefined;
    install();
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    // The anchor does not change while the layer is open.
    const returnTarget = returnFocusRef?.current ?? previous;
    const replaced = overlayStack.open({ id, kind, ...(side ? { side } : {}), closeOnEscape, requestClose: () => onCloseRef.current() });
    for (const entry of replaced) entry.requestClose();
    const element = layerRef.current;
    if (element) layerElements.set(id, element);
    syncInert();
    return () => {
      layerElements.delete(id);
      overlayStack.close(id);
      const target = returnTarget;
      // Return focus only if it is still on the page and nothing else took it meanwhile.
      if (target && target.isConnected && (!document.activeElement || document.activeElement === document.body || element?.contains(document.activeElement))) {
        target.focus({ preventScroll: true });
      }
    };
  }, [open, id, kind, side, closeOnEscape, layerRef, returnFocusRef]);

  useEffect(() => {
    if (!open) return;
    const element = layerRef.current;
    if (!element) return;
    // The header close button is a way out, not where work starts: skip it when choosing.
    const candidates = focusableWithin(trapRef?.current ?? element);
    const target = initialFocusRef?.current ?? candidates.find((el) => !el.hasAttribute("data-overlay-close")) ?? candidates[0] ?? (trapRef?.current ?? element);
    if (!element.contains(document.activeElement)) target.focus({ preventScroll: true });
  }, [open, layerRef, initialFocusRef, trapRef]);

  useEffect(() => {
    const trap = trapRef?.current;
    if (!open || !trap) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const next = trappedFocusTarget(focusableWithin(trap), document.activeElement, event.shiftKey);
      if (next) { event.preventDefault(); next.focus(); }
    };
    trap.addEventListener("keydown", onKeyDown);
    return () => trap.removeEventListener("keydown", onKeyDown);
  }, [open, trapRef]);

  return zIndex;
}
