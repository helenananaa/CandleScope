import { useEffect, useRef } from "react";
import { IconButton, MenuItemButton, moveMenuFocus, useAnchoredPopup } from "../ui/index.js";
import { t } from "../../i18n/index.js";
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
  /** Starred tools: each row gets a star, and F on a focused row toggles it. */
  favorites?: FlyoutFavorites<TId> | null;
}

export interface FlyoutFavorites<TId extends string = string> {
  isFavorite(id: TId): boolean;
  /** False when the tool could not be starred (the list is full or storage failed). */
  toggle(id: TId): boolean;
  full: boolean;
}

const StarIcon = ({ filled }: { filled: boolean }) => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" aria-hidden="true">
    <path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9Z" />
  </svg>
);

export default function ToolFlyout<TId extends string>({
  variants,
  currentId,
  onSelect,
  onClose,
  anchorRef,
  label,
  className = "",
  isVariantDisabled = null,
  favorites = null,
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
        const focusedId = event.target instanceof HTMLElement ? event.target.dataset.toolVariant : undefined;
        if (favorites && focusedId && (event.key === "f" || event.key === "F")
          && !event.altKey && !event.ctrlKey && !event.metaKey) {
          const variant = variants.find((item) => item.id === focusedId);
          if (variant) { event.preventDefault(); favorites.toggle(variant.id); }
          return;
        }
        moveMenuFocus(event, menuRef.current);
      }}>
      {variants.map((variant) => {
        const disabled = Boolean(isVariantDisabled?.(variant));
        const label = drawingVariantLabel(variant);
        const description = drawingVariantDescription(variant);
        const item = (
          <MenuItemButton
            key={variant.id}
            ref={currentId === variant.id && !disabled ? selectedRef : undefined}
            role="menuitemradio"
            aria-checked={currentId === variant.id}
            className={`tool-flyout-item ${currentId === variant.id ? "selected" : ""}`}
            data-tool-variant={variant.id}
            aria-disabled={disabled}
            disabled={disabled}
            icon={variant.icon}
            hint={currentId === variant.id ? "\u2713" : undefined}
            onClick={() => {
              if (disabled) return;
              onSelect(variant.id);
              onClose();
            }}
          >
            <span className="tool-flyout-label-main">{label}</span>
            {description && (
              <span className="tool-flyout-description">{description}</span>
            )}
          </MenuItemButton>
        );
        if (!favorites) return item;
        const starred = favorites.isFavorite(variant.id);
        const starLabel = starred
          ? t("drawing.favorites.remove", { tool: label })
          : favorites.full ? t("drawing.favorites.full") : t("drawing.favorites.add", { tool: label });
        return (
          <div key={variant.id} className="tool-flyout-row" role="none">
            {item}
            <IconButton
              size="sm"
              className="tool-flyout-favorite"
              tabIndex={-1}
              label={starLabel}
              pressed={starred}
              disabled={!starred && favorites.full}
              data-favorite-tool={variant.id}
              icon={<StarIcon filled={starred} />}
              onClick={() => { favorites.toggle(variant.id); }}
            />
          </div>
        );
      })}
    </div>
  );
}
