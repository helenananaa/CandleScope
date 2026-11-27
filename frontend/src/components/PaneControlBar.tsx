import type {
  MouseEvent as ReactMouseEvent,
  PointerEvent as ReactPointerEvent,
} from "react";
import { t } from "../i18n/index.js";
import { useLocale } from "../i18n/useLocale.js";
import { IconButton } from "./ui/index.js";
import type { PaneMoveDirection } from "./paneControlModel.js";

interface PaneControlBarProps {
  paneId: string;
  paneLabel: string;
  canMoveUp: boolean;
  canMoveDown: boolean;
  canCollapse: boolean;
  canMaximize: boolean;
  canDelete: boolean;
  collapsed: boolean;
  hovered: boolean;
  maximized: boolean;
  onMove(direction: PaneMoveDirection): void;
  onToggleCollapse(): void;
  onToggleMaximize(): void;
  onDelete(): void;
}

function PaneIcon({ kind }: { kind: "up" | "down" | "collapse" | "expand" | "maximize" | "restore" | "delete" }) {
  if (kind === "up" || kind === "down") {
    return (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <path d={kind === "up" ? "M5 12.5 10 7l5 5.5" : "m5 7.5 5 5.5 5-5.5"} />
      </svg>
    );
  }
  if (kind === "collapse" || kind === "expand") {
    return (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <path d="M4 10h12" />
        {kind === "collapse" ? (
          <>
            <path d="m7 5 3 3 3-3" />
            <path d="m7 15 3-3 3 3" />
          </>
        ) : (
          <>
            <path d="m7 8 3-3 3 3" />
            <path d="m7 12 3 3 3-3" />
          </>
        )}
      </svg>
    );
  }
  if (kind === "delete") {
    return (
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <path d="M4.5 6h11M8 3.5h4M6.5 6l.7 10h5.6l.7-10M8.5 8.5v5M11.5 8.5v5" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      {kind === "maximize" ? (
        <>
          <path d="M7.5 4H4v3.5M12.5 4H16v3.5M7.5 16H4v-3.5M12.5 16H16v-3.5" />
        </>
      ) : (
        <>
          <path d="M4 7.5h3.5V4M16 7.5h-3.5V4M4 12.5h3.5V16M16 12.5h-3.5V16" />
        </>
      )}
    </svg>
  );
}

function stopPointer(event: ReactPointerEvent<HTMLDivElement>) {
  event.stopPropagation();
}

function stopClick(event: ReactMouseEvent<HTMLDivElement>) {
  event.stopPropagation();
}

export default function PaneControlBar({
  paneId,
  paneLabel,
  canMoveUp,
  canMoveDown,
  canCollapse,
  canMaximize,
  canDelete,
  collapsed,
  hovered,
  maximized,
  onMove,
  onToggleCollapse,
  onToggleMaximize,
  onDelete,
}: PaneControlBarProps) {
  useLocale();
  const title = paneLabel || t("pane.main");
  return (
    <div
      className="pane-control-bar pane-overlay-anchor export-exclude"
      data-pane-id={paneId}
      data-pane-collapsed={collapsed ? "true" : "false"}
      data-pane-hovered={hovered ? "true" : "false"}
      data-pane-maximized={maximized ? "true" : "false"}
      role="toolbar"
      aria-label={t("pane.controls", { title })}
      onPointerDown={stopPointer}
      onClick={stopClick}
    >
      <IconButton
        size="sm"
        className="pane-control-button"
        label={t("pane.moveUpAria", { title })}
        title={canMoveUp ? t("pane.moveUp") : t("pane.moveUpDisabled")}
        icon={<PaneIcon kind="up" />}
        disabled={!canMoveUp}
        onClick={() => onMove("up")}
      />
      <IconButton
        size="sm"
        className="pane-control-button"
        label={t("pane.moveDownAria", { title })}
        title={canMoveDown ? t("pane.moveDown") : t("pane.moveDownDisabled")}
        icon={<PaneIcon kind="down" />}
        disabled={!canMoveDown}
        onClick={() => onMove("down")}
      />
      <IconButton
        size="sm"
        className="pane-control-button"
        label={collapsed ? t("pane.expandAria", { title }) : t("pane.collapseAria", { title })}
        title={collapsed ? t("pane.expand") : t("pane.collapse")}
        icon={<PaneIcon kind={collapsed ? "expand" : "collapse"} />}
        pressed={collapsed}
        disabled={!canCollapse}
        onClick={onToggleCollapse}
      />
      <IconButton
        size="sm"
        className="pane-control-button"
        label={maximized ? t("pane.exitFullscreenAria", { title }) : t("pane.fullscreenAria", { title })}
        title={canMaximize ? (maximized ? t("pane.exitFullscreen") : t("pane.fullscreen")) : t("pane.onlyPane")}
        icon={<PaneIcon kind={maximized ? "restore" : "maximize"} />}
        pressed={maximized}
        disabled={!canMaximize}
        onClick={onToggleMaximize}
      />
      <IconButton
        size="sm"
        variant="danger"
        className="pane-control-button"
        label={t("pane.deleteAria", { title })}
        title={canDelete ? t("pane.delete") : t("pane.cannotDeleteMain")}
        icon={<PaneIcon kind="delete" />}
        disabled={!canDelete}
        onClick={onDelete}
      />
    </div>
  );
}
