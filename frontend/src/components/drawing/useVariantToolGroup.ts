import { useCallback, useEffect, useRef, useState } from "react";
import type { Dispatch, MouseEvent, SetStateAction } from "react";
import { drawingVariantLabel } from "./drawingToolbarI18n.js";
import type { ToolbarVariant } from "./drawingToolbarDefinitions.js";
import type { DrawingToolId } from "../../features/drawings/drawingTypes.js";

export interface VariantToolGroupOptions<TId extends DrawingToolId, TKey extends string> {
  readonly activeTool: DrawingToolId | null;
  readonly flyoutKey: TKey;
  readonly initialVariant: TId;
  readonly variants: readonly ToolbarVariant<TId>[];
  onToolChange(tool: DrawingToolId | null): void;
  readonly setFlyoutOpen: Dispatch<SetStateAction<TKey | null>>;
}

/**
 * One toolbar button with a variant flyout: a click arms the last variant (a
 * second click disarms it), a double-click, right-click or keyboard menu opens
 * the variants. Same gestures as the line, shape and position groups.
 */
export function useVariantToolGroup<TId extends DrawingToolId, TKey extends string>({
  activeTool,
  flyoutKey,
  initialVariant,
  variants,
  onToolChange,
  setFlyoutOpen,
}: VariantToolGroupOptions<TId, TKey>) {
  const [variant, setVariant] = useState<TId>(initialVariant);
  const anchorRef = useRef<HTMLDivElement | null>(null);
  const clickTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeVariant = variants.find((item) => item.id === activeTool);
  const active = activeVariant != null;
  const currentId = activeVariant?.id ?? variant;
  const current = variants.find((item) => item.id === currentId) ?? variants[0];

  const clearClickTimer = useCallback(() => {
    if (!clickTimerRef.current) return;
    clearTimeout(clickTimerRef.current);
    clickTimerRef.current = null;
  }, []);
  useEffect(() => clearClickTimer, [clearClickTimer]);

  const onClick = useCallback((event: MouseEvent<HTMLButtonElement>) => {
    if (event?.detail > 1) return;
    if (!active) {
      onToolChange(variant);
      setFlyoutOpen(null);
      return;
    }
    if (clickTimerRef.current) return;
    clickTimerRef.current = setTimeout(() => {
      clickTimerRef.current = null;
      onToolChange(null);
      setFlyoutOpen(null);
    }, 200);
  }, [active, onToolChange, setFlyoutOpen, variant]);

  const toggleFlyout = useCallback(() => {
    clearClickTimer();
    setFlyoutOpen((prev) => (prev === flyoutKey ? null : flyoutKey));
  }, [clearClickTimer, flyoutKey, setFlyoutOpen]);

  const onContextMenu = useCallback((event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    toggleFlyout();
  }, [toggleFlyout]);

  const onSelect = useCallback((id: TId) => {
    setVariant(id);
    onToolChange(id);
  }, [onToolChange]);

  return {
    active,
    anchorRef,
    currentId,
    icon: current?.icon ?? null,
    label: current ? drawingVariantLabel(current) : currentId,
    onClick,
    onContextMenu,
    onDoubleClick: toggleFlyout,
    onSelect,
  };
}
