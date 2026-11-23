import { useCallback, useEffect } from "react";
import type { MutableRefObject } from "react";
import type { ScreenPoint } from "./drawingTypes.js";
import {
  subscribeSharedDrawingDocumentEvent,
} from "./sharedDrawingDocumentEventHub.js";

export type DrawingDomPointerEvent = MouseEvent | PointerEvent | TouchEvent;
export type DrawingPointerHandler = (event: DrawingDomPointerEvent) => void;

export function getChartPointerPosition(
  chartContainerRef: MutableRefObject<HTMLElement | null> | null | undefined,
  event: DrawingDomPointerEvent,
  rectOverride: DOMRect | null = null,
): ScreenPoint | null {
  const container = chartContainerRef?.current;
  if (!container) return null;
  const rect = rectOverride || container.getBoundingClientRect();
  const clientX = "touches" in event ? event.touches[0]?.clientX : event.clientX;
  const clientY = "touches" in event ? event.touches[0]?.clientY : event.clientY;
  if (clientX == null || clientY == null) return null;
  return { x: clientX - rect.left, y: clientY - rect.top };
}

export function useChartPointerPosition(
  chartContainerRef: MutableRefObject<HTMLElement | null>,
): (event: DrawingDomPointerEvent, rectOverride?: DOMRect | null) => ScreenPoint | null {
  return useCallback(
    (event: DrawingDomPointerEvent, rectOverride: DOMRect | null = null) => (
      getChartPointerPosition(chartContainerRef, event, rectOverride)
    ),
    [chartContainerRef],
  );
}

export function useDrawingPointerEvents({
  chartContainerRef,
  handleDblClick,
  handleContextMenu,
  handleMouseDown,
  handleMouseLeave,
  handleMouseMove,
  handleMouseUp,
  handlePointerCancel = handleMouseUp,
  handleWindowBlur,
}: {
  chartContainerRef: MutableRefObject<HTMLElement | null>;
  handleDblClick: (event: MouseEvent) => void;
  handleContextMenu: (event: MouseEvent) => void;
  handleMouseDown: DrawingPointerHandler;
  handleMouseLeave: DrawingPointerHandler;
  handleMouseMove: DrawingPointerHandler;
  handleMouseUp: DrawingPointerHandler;
  handlePointerCancel?: DrawingPointerHandler;
  handleWindowBlur?: (() => void) | undefined;
}): void {
  useEffect(() => {
    const container = chartContainerRef?.current;
    if (!container) return undefined;

    const supportsPointerEvents = typeof window !== "undefined" && "PointerEvent" in window;
    const sharedDocumentEventCleanups: Array<() => void> = [];

    // A touch whose pointerdown the drawing claims (it prevents the default) belongs to the drawing
    // to its end. Its touch events stop here, before the chart's own touch handling pans or scales,
    // and their default is prevented, so the browser does not take the touch over as a scroll and
    // cancel the pointer partway through the stroke.
    let claimedTouches = 0;
    const handlePointerDown = (event: PointerEvent) => {
      handleMouseDown(event);
      if (event.pointerType === "touch" && event.defaultPrevented) claimedTouches += 1;
    };
    const holdClaimedTouch = (event: TouchEvent) => {
      if (claimedTouches === 0) return;
      if (event.cancelable) event.preventDefault();
      event.stopPropagation();
      if ((event.type === "touchend" || event.type === "touchcancel") && event.touches.length === 0) {
        claimedTouches = 0;
      }
    };
    const touchOptions = { capture: true, passive: false } as const;

    if (supportsPointerEvents) {
      container.addEventListener("pointerdown", handlePointerDown, true);
      for (const type of ["touchstart", "touchmove", "touchend", "touchcancel"] as const) {
        container.addEventListener(type, holdClaimedTouch, touchOptions);
      }
      sharedDocumentEventCleanups.push(
        subscribeSharedDrawingDocumentEvent(
          document,
          "pointermove",
          (event) => handleMouseMove(event as PointerEvent),
        ),
        subscribeSharedDrawingDocumentEvent(
          document,
          "pointerup",
          (event) => handleMouseUp(event as PointerEvent),
        ),
        subscribeSharedDrawingDocumentEvent(
          document,
          "pointercancel",
          (event) => handlePointerCancel(event as PointerEvent),
        ),
      );
      container.addEventListener("pointerleave", handleMouseLeave);
    } else {
      container.addEventListener("mousedown", handleMouseDown, true);
      sharedDocumentEventCleanups.push(
        subscribeSharedDrawingDocumentEvent(
          document,
          "mousemove",
          (event) => handleMouseMove(event as MouseEvent),
        ),
        subscribeSharedDrawingDocumentEvent(
          document,
          "mouseup",
          (event) => handleMouseUp(event as MouseEvent),
        ),
      );
      container.addEventListener("mouseleave", handleMouseLeave);
      container.addEventListener("touchstart", handleMouseDown, { passive: false, capture: true });
      container.addEventListener("touchmove", handleMouseMove, { passive: false });
      container.addEventListener("touchend", handleMouseUp);
      container.addEventListener("touchcancel", handlePointerCancel);
    }

    container.addEventListener("dblclick", handleDblClick);
    container.addEventListener("contextmenu", handleContextMenu);
    if (handleWindowBlur) window.addEventListener("blur", handleWindowBlur);

    return () => {
      if (supportsPointerEvents) {
        container.removeEventListener("pointerdown", handlePointerDown, true);
        for (const type of ["touchstart", "touchmove", "touchend", "touchcancel"] as const) {
          container.removeEventListener(type, holdClaimedTouch, touchOptions);
        }
        container.removeEventListener("pointerleave", handleMouseLeave);
      } else {
        container.removeEventListener("mousedown", handleMouseDown, true);
        container.removeEventListener("mouseleave", handleMouseLeave);
        container.removeEventListener("touchstart", handleMouseDown, true);
        container.removeEventListener("touchmove", handleMouseMove);
        container.removeEventListener("touchend", handleMouseUp);
        container.removeEventListener("touchcancel", handlePointerCancel);
      }
      for (const cleanup of sharedDocumentEventCleanups) cleanup();

      container.removeEventListener("dblclick", handleDblClick);
      container.removeEventListener("contextmenu", handleContextMenu);
      if (handleWindowBlur) window.removeEventListener("blur", handleWindowBlur);
    };
  }, [
    chartContainerRef,
    handleContextMenu,
    handleDblClick,
    handleMouseDown,
    handleMouseLeave,
    handleMouseMove,
    handleMouseUp,
    handlePointerCancel,
    handleWindowBlur,
  ]);
}
