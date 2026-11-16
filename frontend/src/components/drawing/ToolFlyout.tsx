import { useEffect, useRef } from "react";
import { moveMenuFocus, useAnchoredPopup } from "../ui/index.js";
import type { RefObject } from "react";
import type { ToolbarVariant } from "./drawingToolbarDefinitions.js";
import { drawingVariantDescription, drawingVariantLabel } from "./drawingToolbarI18n.js";

export interface ToolFlyoutProps<TId extends string = string> {
  variants: readonly ToolbarVariant<TId>[];
  currentId: TId;
  onSelect(id: TId): void;
  onClose(): void;
  anchorRef: RefObject<HTMLDivElement | null>;
  /** The menu's name: the tool it belongs to. */
  label?: string;
  className?: string;
  isVariantDisabled?: ((variant: ToolbarVariant<TId>) => boolean) | null;
}

export default function ToolFlyout<TId extends string>({
  variants,
  currentId,
  onSelect,
  onClose,
  anchorRef,
  label,
  className = "",
  isVariantDisabled = null,
}: ToolFlyoutProps<TId>) {
  const menuRef = useRef<HTMLDivElement | null>(null);
  const selectedRef = useRef<HTMLButtonElement | null>(null);
  // Escape closes it; focus starts on the chosen variant and goes back to the tool's button.
  useAnchoredPopup({ open: true, onClose, popupRef: menuRef, initialFocusRef: selectedRef });

  useEffect(() => {
    const handler = (event: MouseEvent) => {
      if (!(event.target instanceof Node)) return;
      if (
        menuRef.current
        && !menuRef.current.contains(event.target)
        && anchorRef.current
        && !anchorRef.current.contains(event.target)
      ) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [anchorRef, onClose]);

  return (
    <div className={`tool-flyout ${className}`.trim()} ref={menuRef} role="menu" aria-label={label}
      onKeyDown={(event) => {
        if (event.key === "Tab") { event.preventDefault(); onClose(); return; }
        moveMenuFocus(event, menuRef.current);
      }}>
      {variants.map((variant) => {
        const disabled = Boolean(isVariantDisabled?.(variant));
        const label = drawingVariantLabel(variant);
        const description = drawingVariantDescription(variant);
        return (
          <button
            type="button"
            key={variant.id}
            ref={currentId === variant.id && !disabled ? selectedRef : undefined}
            role="menuitemradio"
            aria-checked={currentId === variant.id}
            className={`tool-flyout-item ${currentId === variant.id ? "selected" : ""}`}
            data-tool-variant={variant.id}
            aria-disabled={disabled}
            disabled={disabled}
            onClick={() => {
              if (disabled) return;
              onSelect(variant.id);
              onClose();
            }}
          >
            <span className="tool-flyout-icon">{variant.icon}</span>
            <span className="tool-flyout-label">
              <span className="tool-flyout-label-main">{label}</span>
              {description && (
                <span className="tool-flyout-description">{description}</span>
              )}
            </span>
            {currentId === variant.id && <span className="tool-flyout-check" aria-hidden="true">&#10003;</span>}
          </button>
        );
      })}
    </div>
  );
}
