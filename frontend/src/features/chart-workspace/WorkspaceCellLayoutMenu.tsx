import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import type { ReactNode } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import type {
  ChartCellCreationMode,
  ChartCellId,
  ChartWorkspaceSplitDirection,
} from "./chartWorkspaceTypes.js";
import { Icon } from "../../components/icons/Icon.js";
import { Button, IconButton, useAnchoredPopup } from "../../components/ui/index.js";

export interface WorkspaceCellLayoutMenuProps {
  cellId: ChartCellId;
  layoutCellIds: readonly ChartCellId[];
  maxCellsPerWindow?: number;
  disabled?: boolean;
  portal?: boolean;
  children?: ReactNode;
  /** The chart's appearance controls, shown first in the menu. */
  appearance?: ReactNode;
  /** The chart has its own appearance: a marker beside the menu button opens the menu. */
  customized?: boolean;
  onSplit(
    cellId: ChartCellId,
    direction: ChartWorkspaceSplitDirection,
    creationMode: ChartCellCreationMode,
  ): void;
  onClose(cellId: ChartCellId): void;
  onSwap(firstCellId: ChartCellId, secondCellId: ChartCellId): void;
}

export default function WorkspaceCellLayoutMenu({
  cellId,
  layoutCellIds,
  maxCellsPerWindow = 4,
  disabled = false,
  portal = false,
  children,
  appearance,
  customized = false,
  onSplit,
  onClose,
  onSwap,
}: WorkspaceCellLayoutMenuProps) {
  useLocale();
  const [open, setOpen] = useState(false);
  const [creationMode, setCreationMode] = useState<ChartCellCreationMode>("copy");
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);
  const [position, setPosition] = useState({ top: 0, right: 0, maxHeight: 0 });
  const cellNumber = (id: ChartCellId) => String(layoutCellIds.indexOf(id) + 1);
  // Layout editing can be off (a locked layout, a maximized chart) while the chart's appearance stays editable.
  const layoutDisabled = disabled;
  const menuDisabled = disabled && !appearance;
  const canSplit = !layoutDisabled && layoutCellIds.length < maxCellsPerWindow;
  const canClose = !layoutDisabled && layoutCellIds.length > 1;
  const swapTargets = layoutDisabled ? [] : layoutCellIds.filter((candidate) => candidate !== cellId);
  const menuOpen = open && !menuDisabled;
  const closeMenu = useCallback(() => setOpen(false), []);
  // On the overlay stack: Escape closes it, focus moves in and back to the trigger.
  useAnchoredPopup({ open: menuOpen, onClose: closeMenu, popupRef: popoverRef, triggerRef });

  useEffect(() => {
    if (!menuOpen) return undefined;
    const handlePointerDown = (event: PointerEvent) => {
      if (rootRef.current?.contains(event.target as Node)) return;
      if (popoverRef.current?.contains(event.target as Node)) return;
      setOpen(false);
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [menuOpen]);

  const runAndClose = (action: () => void) => {
    action();
    setOpen(false);
  };
  const renderPopover = (content: ReactNode) => portal ? createPortal(content, document.body) : content;

  return (
    <div
      ref={rootRef}
      className="workspace-cell-layout-menu"
      onDoubleClick={(event) => event.stopPropagation()}
    >
      {customized && (
        <IconButton
          size="sm"
          className="chart-appearance-marker"
          label={t("chartAppearance.marker")}
          icon={<Icon name="palette" size={13} />}
          disabled={menuDisabled}
          onClick={(event) => {
            event.stopPropagation();
            triggerRef.current?.click();
          }}
        />
      )}
      <IconButton
        ref={triggerRef}
        size="sm"
        className="multi-chart-cell-layout-trigger"
        label={t("workspace.cellMenu", { n: cellNumber(cellId) })}
        icon={<Icon name="more" size={16} />}
        aria-haspopup="dialog"
        aria-expanded={menuOpen}
        title={t("workspace.cellMenuTitle")}
        disabled={menuDisabled}
        onClick={(event) => {
          event.stopPropagation();
          if (portal) {
            // Below the button, kept inside the window; a menu taller than the room left scrolls.
            // It sits above drawers and under modals and toasts.
            const rect = event.currentTarget.getBoundingClientRect();
            const top = Math.max(8, Math.min(rect.bottom + 7, window.innerHeight - 248));
            setPosition({
              top,
              right: Math.max(8, Math.min(window.innerWidth - rect.right, window.innerWidth - 244)),
              maxHeight: window.innerHeight - top - 8,
            });
          }
          setOpen((value) => !value);
        }}
      />
      {menuOpen && renderPopover(
        <div
          ref={popoverRef}
          className="workspace-cell-layout-popover"
          style={portal ? { position: "fixed", ...position, zIndex: "calc(var(--z-modal) - 1)", overflowY: "auto" } : undefined}
          role="dialog"
          aria-label={t("workspace.cellMenu", { n: cellNumber(cellId) })}
          onPointerDown={(event) => event.stopPropagation()}
        >
          {appearance}
          <strong>{t("workspace.cellLayout", { n: cellNumber(cellId) })}</strong>
          <fieldset disabled={!canSplit}>
            <legend>{t("workspace.newContent")}</legend>
            <label>
              <input
                type="radio"
                name={`${cellId}-creation-mode`}
                value="copy"
                checked={creationMode === "copy"}
                onChange={() => setCreationMode("copy")}
              />
              {t("workspace.copyConfig")}
            </label>
            <label>
              <input
                type="radio"
                name={`${cellId}-creation-mode`}
                value="blank"
                checked={creationMode === "blank"}
                onChange={() => setCreationMode("blank")}
              />
              {t("workspace.blankChart")}
            </label>
          </fieldset>
          <div className="workspace-cell-layout-actions">
            <Button size="sm" disabled={!canSplit} onClick={() => runAndClose(() => onSplit(cellId, "columns", creationMode))}>
              {t("workspace.splitRight")}
            </Button>
            <Button size="sm" disabled={!canSplit} onClick={() => runAndClose(() => onSplit(cellId, "rows", creationMode))}>
              {t("workspace.splitDown")}
            </Button>
          </div>
          {swapTargets.length > 0 && (
            <div className="workspace-cell-swap-actions" aria-label={t("workspace.swap")}>
              <span>{t("workspace.swapLabel")}</span>
              <div>
                {swapTargets.map((targetCellId) => (
                  <Button key={targetCellId} size="sm" onClick={() => runAndClose(() => onSwap(cellId, targetCellId))}>
                    {t("workspace.cellN", { n: cellNumber(targetCellId) })}
                  </Button>
                ))}
              </div>
            </div>
          )}
          {children}
          <Button size="sm" variant="danger" disabled={!canClose} onClick={() => runAndClose(() => onClose(cellId))}>
            {canClose || layoutDisabled ? t("workspace.closeChart") : t("workspace.keepOneChart")}
          </Button>
        </div>
      )}
    </div>
  );
}
