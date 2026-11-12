import {
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

  useEffect(() => {
    if (!menuOpen) return undefined;
    const handlePointerDown = (event: PointerEvent) => {
      if (rootRef.current?.contains(event.target as Node)) return;
      if (popoverRef.current?.contains(event.target as Node)) return;
      setOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
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
        <button
          type="button"
          className="chart-appearance-marker"
          aria-label={t("chartAppearance.marker")}
          title={t("chartAppearance.marker")}
          disabled={menuDisabled}
          onClick={(event) => {
            event.stopPropagation();
            triggerRef.current?.click();
          }}
        >
          <Icon name="palette" size={13} />
        </button>
      )}
      <button
        ref={triggerRef}
        type="button"
        className="multi-chart-cell-layout-trigger"
        aria-label={t("workspace.cellMenu", { n: cellNumber(cellId) })}
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
      >
        <Icon name="more" size={16} />
      </button>
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
            <button
              type="button"
              disabled={!canSplit}
              onClick={() => runAndClose(() => onSplit(cellId, "columns", creationMode))}
            >
              {t("workspace.splitRight")}
            </button>
            <button
              type="button"
              disabled={!canSplit}
              onClick={() => runAndClose(() => onSplit(cellId, "rows", creationMode))}
            >
              {t("workspace.splitDown")}
            </button>
          </div>
          {swapTargets.length > 0 && (
            <div className="workspace-cell-swap-actions" aria-label={t("workspace.swap")}>
              <span>{t("workspace.swapLabel")}</span>
              <div>
                {swapTargets.map((targetCellId) => (
                  <button
                    key={targetCellId}
                    type="button"
                    onClick={() => runAndClose(() => onSwap(cellId, targetCellId))}
                  >
                    {t("workspace.cellN", { n: cellNumber(targetCellId) })}
                  </button>
                ))}
              </div>
            </div>
          )}
          {children}
          <button
            type="button"
            className="workspace-cell-close-action"
            disabled={!canClose}
            onClick={() => runAndClose(() => onClose(cellId))}
          >
            {canClose || layoutDisabled ? t("workspace.closeChart") : t("workspace.keepOneChart")}
          </button>
        </div>
      )}
    </div>
  );
}
