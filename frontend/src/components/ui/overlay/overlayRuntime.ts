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

/** Any managed layer is open. Page shortcuts that use Escape yield while one is. */
export function hasOpenOverlay(): boolean {
  return overlayStack.top() !== undefined;
}

type EscapeEvent = Pick<KeyboardEvent, "key" | "isComposing" | "keyCode" | "defaultPrevented" | "cancelBubble">;

/**
 * Whether Escape should close the top layer, decided after every other handler ran:
 * a widget inside the layer (an editor, a nested picker, a rename field) or a page popover
 * that used the key prevents the default or stops propagation, and a native modal
 * <dialog> handles its own Escape.
 */
export function escapeClosesTopLayer(event: EscapeEvent, state: { layersOpen: boolean; nativeModalOpen: boolean }): boolean {
  if (event.key !== "Escape" || event.isComposing || event.keyCode === 229) return false;
  if (event.defaultPrevented || event.cancelBubble) return false;
  return state.layersOpen && !state.nativeModalOpen;
}

function nativeModalOpen(): boolean {
  try {
    return document.querySelector("dialog:modal") !== null;
  } catch {
    return false;
  }
}

let installed = false;
function install() {
  if (installed || typeof document === "undefined") return;
  installed = true;
  window.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !hasOpenOverlay()) return;
    // A listener added to window during this dispatch runs after every listener already
    // there, so the stack decides last. Removed on the next tick if propagation stopped.
    const afterOthers = (late: KeyboardEvent) => {
      window.removeEventListener("keydown", afterOthers);
      if (late !== event) return;
      if (!escapeClosesTopLayer(late, { layersOpen: hasOpenOverlay(), nativeModalOpen: nativeModalOpen() })) return;
      late.preventDefault();
      overlayStack.escape();
    };
    window.addEventListener("keydown", afterOthers);
    setTimeout(() => window.removeEventListener("keydown", afterOthers), 0);
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

function isStartingControl(element: HTMLElement): boolean {
  return !element.hasAttribute("data-overlay-close") && element.getAttribute("role") !== "separator";
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

/** Registers a layer while open and returns its z-index. The layer element must unmount when it closes. */
export function useOverlayLayer({ open, kind, side, onClose, closeOnEscape = true, layerRef, initialFocusRef, trapRef, returnFocusRef }: OverlayLayerOptions): number | undefined {
  const id = useId();
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  // Read on each Escape, so changing it does not re-register the layer (which would move focus).
  const closeOnEscapeRef = useRef(closeOnEscape);
  closeOnEscapeRef.current = closeOnEscape;
  const zIndex = useSyncExternalStore(overlayStack.subscribe, () => overlayStack.zIndex(id), () => undefined);

  // Captured once per opening: StrictMode re-runs the effect after focus moved inside.
  const returnTargetRef = useRef<HTMLElement | null | undefined>(undefined);

  useLayoutEffect(() => {
    if (!open) {
      returnTargetRef.current = undefined;
      return undefined;
    }
    install();
    if (returnTargetRef.current === undefined) {
      const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      // The anchor does not change while the layer is open.
      returnTargetRef.current = returnFocusRef?.current ?? previous;
    }
    const returnTarget = returnTargetRef.current;
    const replaced = overlayStack.open({ id, kind, ...(side ? { side } : {}), closeOnEscape: () => closeOnEscapeRef.current, requestClose: () => onCloseRef.current() });
    for (const entry of replaced) entry.requestClose();
    const element = layerRef.current;
    if (element) layerElements.set(id, element);
    syncInert();
    return () => {
      layerElements.delete(id);
      overlayStack.close(id);
      const target = returnTarget;
      const active = document.activeElement;
      // Only when focus was in the layer or nowhere, so a click elsewhere keeps its focus.
      const returnFocus = !active || active === document.body || !!element?.contains(active);
      // After the commit: the opener may only become focusable in it (a panel that was
      // hidden while this layer was open). Skip if the layer is still on screen (effects
      // re-ran; it did not close) or something else took focus meanwhile.
      if (returnFocus) queueMicrotask(() => {
        if (element?.isConnected) return;
        const now = document.activeElement;
        if (!target?.isConnected || (now && now !== document.body && !element?.contains(now))) return;
        target.focus({ preventScroll: true });
      });
    };
  }, [open, id, kind, side, layerRef, returnFocusRef]);

  useEffect(() => {
    if (!open) return;
    const element = layerRef.current;
    if (!element) return;
    // Close buttons and resize handles are ways out or chrome, not where work starts.
    const candidates = focusableWithin(trapRef?.current ?? element);
    const target = initialFocusRef?.current ?? candidates.find(isStartingControl) ?? candidates[0] ?? (trapRef?.current ?? element);
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
