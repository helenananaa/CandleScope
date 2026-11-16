// Places a popover next to its anchor, flipping to the other side and clamping to the viewport.

export interface Rect { top: number; left: number; width: number; height: number }
export interface Size { width: number; height: number }
export type Placement = "bottom-start" | "bottom-end" | "top-start" | "top-end" | "bottom" | "top";

export interface PlacedPopover {
  top: number;
  left: number;
  placement: Placement;
  /** Height available on the chosen side; the popover scrolls beyond it. */
  maxHeight: number;
}

const MARGIN = 8;

export function placePopover(anchor: Rect, popover: Size, viewport: Size, placement: Placement = "bottom-start", gap = 6): PlacedPopover {
  const wantsTop = placement.startsWith("top");
  const below = viewport.height - (anchor.top + anchor.height) - gap - MARGIN;
  const above = anchor.top - gap - MARGIN;
  // Flip when the preferred side is too short and the other side has more room.
  const useTop = wantsTop ? !(above < popover.height && below > above) : below < popover.height && above > below;
  const side = useTop ? "top" : "bottom";
  const align = placement.endsWith("-end") ? "end" : placement === "top" || placement === "bottom" ? "center" : "start";
  let left = align === "start" ? anchor.left : align === "end" ? anchor.left + anchor.width - popover.width : anchor.left + (anchor.width - popover.width) / 2;
  left = Math.min(Math.max(left, MARGIN), Math.max(MARGIN, viewport.width - popover.width - MARGIN));
  const maxHeight = Math.max(0, useTop ? above : below);
  const height = Math.min(popover.height, maxHeight);
  const top = useTop ? anchor.top - gap - height : anchor.top + anchor.height + gap;
  const resolved = (align === "center" ? side : `${side}-${align}`) as Placement;
  return { top: Math.round(top), left: Math.round(left), placement: resolved, maxHeight: Math.round(maxHeight) };
}
