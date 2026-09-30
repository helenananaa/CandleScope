import { useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent, RefObject } from "react";
import { clampEditorPosition, placeEditorPopover, type EditorPoint } from "./drawingEditorLayout.js";

// Per chart container, across object changes. Never persist UI position in the drawing document.
const positions = new WeakMap<HTMLElement, EditorPoint>();
function rememberPosition(parent: HTMLElement, point: EditorPoint) { positions.set(parent, point); }

export function useDrawingToolbarPosition() {
  const root = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<EditorPoint | null>(null);
  const drag = useRef<{ pointerId: number; x: number; y: number; origin: EditorPoint } | null>(null);
  const current = useRef<EditorPoint | null>(null);
  const parent = () => root.current?.offsetParent as HTMLElement | null;
  const fit = (point: EditorPoint) => {
    const container = parent();
    if (!container || !root.current) return point;
    return clampEditorPosition(point, { width: root.current.offsetWidth, height: root.current.offsetHeight }, { width: container.clientWidth, height: container.clientHeight });
  };
  const home = () => fit({ x: (parent()?.clientWidth ?? 0) - (root.current?.offsetWidth ?? 0) - 72, y: 44 });
  const move = (point: EditorPoint) => {
    const next = fit(point);
    current.current = next;
    setPosition(next);
    return next;
  };
  useLayoutEffect(() => {
    const element = root.current;
    const container = element?.offsetParent;
    if (!element || !(container instanceof HTMLElement)) return;
    const place = () => {
      const preferred = positions.get(container) ?? { x: container.clientWidth - element.offsetWidth - 72, y: 44 };
      const next = clampEditorPosition(preferred, { width: element.offsetWidth, height: element.offsetHeight }, { width: container.clientWidth, height: container.clientHeight });
      current.current = next;
      setPosition((previous) => previous?.x === next.x && previous?.y === next.y ? previous : next);
    };
    place();
    const observer = new ResizeObserver(place);
    observer.observe(element);
    observer.observe(container);
    return () => observer.disconnect();
  }, []);
  return {
    root,
    style: position ? { left: position.x, top: position.y, right: "auto" } : undefined,
    handle: {
      onPointerDown(event: PointerEvent<HTMLButtonElement>) {
        if (event.button !== 0 || !current.current) return;
        event.preventDefault(); event.stopPropagation();
        event.currentTarget.focus();
        drag.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, origin: current.current };
        event.currentTarget.setPointerCapture(event.pointerId);
      },
      onPointerMove(event: PointerEvent<HTMLButtonElement>) {
        const start = drag.current;
        if (!start || start.pointerId !== event.pointerId) return;
        move({ x: start.origin.x + event.clientX - start.x, y: start.origin.y + event.clientY - start.y });
      },
      onPointerUp(event: PointerEvent<HTMLButtonElement>) {
        if (!drag.current || drag.current.pointerId !== event.pointerId) return;
        const container = parent();
        if (container && current.current) rememberPosition(container, current.current);
        drag.current = null;
        event.currentTarget.releasePointerCapture(event.pointerId);
      },
      onPointerCancel() { if (drag.current) move(drag.current.origin); drag.current = null; },
      onLostPointerCapture() { if (drag.current) move(drag.current.origin); drag.current = null; },
      onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
        const point = current.current;
        const container = parent();
        if (!point || !container) return;
        if (event.key === "Escape" && drag.current) {
          event.preventDefault(); move(drag.current.origin); drag.current = null; return;
        }
        const step = event.shiftKey ? 1 : 10;
        const delta = ({ ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] } as Record<string, [number, number]>)[event.key];
        if (event.key === "Home") {
          event.preventDefault(); event.stopPropagation();
          rememberPosition(container, move(home()));
        } else if (delta) {
          event.preventDefault(); event.stopPropagation();
          rememberPosition(container, move({ x: point.x + delta[0], y: point.y + delta[1] }));
        }
      },
    },
  };
}

/** Native top-layer surfaces escape chart clipping but stay anchored to their trigger. */
export function useDrawingSurfacePlacement(
  surface: RefObject<HTMLElement | null>, anchor: RefObject<HTMLElement | null>, open: boolean,
) {
  const [position, setPosition] = useState<EditorPoint | null>(null);
  useLayoutEffect(() => {
    const element = surface.current, trigger = anchor.current;
    if (!open || !element || !trigger) return;
    if (element instanceof HTMLDialogElement && !element.open) element.showModal();
    const place = () => {
      const next = placeEditorPopover(trigger.getBoundingClientRect(), element.getBoundingClientRect(), { width: document.documentElement.clientWidth, height: window.innerHeight });
      setPosition((previous) => previous?.x === next.x && previous?.y === next.y ? previous : next);
    };
    place();
    const observer = new ResizeObserver(place);
    observer.observe(element);
    observer.observe(trigger);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, surface, anchor]);
  return position ? { left: position.x, top: position.y } : undefined;
}
