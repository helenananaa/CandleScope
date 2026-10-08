import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import {
  chartWorkspaceTemplateCellCount,
  createChartWorkspaceLayoutTree,
} from "./chartWorkspaceLayout.js";
import { chartWorkspaceLayoutLabel } from "./chartWorkspaceI18n.js";
import { CHART_WORKSPACE_TEMPLATE_IDS } from "./chartWorkspaceTypes.js";
import type {
  ChartWorkspaceLayout,
  ChartWorkspaceLayoutNode,
  ChartWorkspaceTemplateId,
} from "./chartWorkspaceTypes.js";
import { Icon } from "../../components/icons/Icon.js";

interface LayoutRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

const THUMB_WIDTH = 20;
const THUMB_HEIGHT = 14;
const THUMB_GAP = 1.5;

function layoutRects(node: ChartWorkspaceLayoutNode, rect: LayoutRect, out: LayoutRect[]): LayoutRect[] {
  if (node.kind === "cell") {
    out.push(rect);
    return out;
  }
  const half = THUMB_GAP / 2;
  if (node.direction === "columns") {
    const split = rect.width * node.ratio;
    layoutRects(node.first, { ...rect, width: split - half }, out);
    layoutRects(node.second, { ...rect, x: rect.x + split + half, width: rect.width - split - half }, out);
  } else {
    const split = rect.height * node.ratio;
    layoutRects(node.first, { ...rect, height: split - half }, out);
    layoutRects(node.second, { ...rect, y: rect.y + split + half, height: rect.height - split - half }, out);
  }
  return out;
}

/** Miniature of a layout tree, drawn from the same geometry the workspace uses. */
export function LayoutThumbnail({ tree }: { tree: ChartWorkspaceLayoutNode }) {
  const rects = layoutRects(tree, { x: 0.5, y: 0.5, width: THUMB_WIDTH - 1, height: THUMB_HEIGHT - 1 }, []);
  return (
    <svg
      className="workspace-layout-thumb"
      width={THUMB_WIDTH}
      height={THUMB_HEIGHT}
      viewBox={`0 0 ${THUMB_WIDTH} ${THUMB_HEIGHT}`}
      aria-hidden="true"
    >
      {rects.map((rect, index) => (
        <rect
          key={index}
          x={rect.x}
          y={rect.y}
          width={Math.max(rect.width, 0.5)}
          height={Math.max(rect.height, 0.5)}
          rx={1}
        />
      ))}
    </svg>
  );
}

export interface WorkspaceLayoutPickerProps {
  tree: ChartWorkspaceLayoutNode;
  layout: ChartWorkspaceLayout;
  cellCount: number;
  maxCellsPerWindow: number;
  ready: boolean;
  locked: boolean;
  saveState?: string;
  onSelectLayout(layout: ChartWorkspaceTemplateId): void;
  onOpenManager(): void;
  onPreloadManager?(): void;
}

/** Top-bar layout control: one click to apply a template to the current workspace. */
function WorkspaceLayoutPicker({
  tree,
  layout,
  cellCount,
  maxCellsPerWindow,
  ready,
  locked,
  saveState,
  onSelectLayout,
  onOpenManager,
  onPreloadManager,
}: WorkspaceLayoutPickerProps) {
  useLocale();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);

  const templates = useMemo(() => CHART_WORKSPACE_TEMPLATE_IDS
    .filter((templateId) => chartWorkspaceTemplateCellCount(templateId) <= maxCellsPerWindow)
    .map((templateId) => ({ id: templateId, tree: createChartWorkspaceLayoutTree(templateId) })),
  [maxCellsPerWindow]);

  const close = useCallback((restoreFocus: boolean) => {
    setOpen(false);
    if (restoreFocus) triggerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const handlePointerDown = (event: MouseEvent) => {
      if (event.target instanceof Node && rootRef.current?.contains(event.target)) return;
      close(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      close(true);
    };
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown, true);
    const focusTarget = panelRef.current?.querySelector<HTMLButtonElement>(
      "button[aria-pressed='true']:not(:disabled), button:not(:disabled)",
    );
    focusTarget?.focus();
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown, true);
    };
  }, [close, open]);

  const handleGridKeyDown = useCallback((event: ReactKeyboardEvent<HTMLDivElement>) => {
    const keys: Record<string, number> = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
    const step = keys[event.key];
    if (step === undefined) return;
    const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("button:not(:disabled)"));
    if (buttons.length === 0) return;
    event.preventDefault();
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    buttons[(index + step + buttons.length) % buttons.length]?.focus();
  }, []);

  const currentLabel = chartWorkspaceLayoutLabel(layout);

  return (
    <div className="workspace-layout-picker" ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className={`ui-control workspace-layout-trigger ${open ? "is-active" : ""}`}
        data-save-state={saveState}
        onPointerEnter={onPreloadManager}
        onFocus={onPreloadManager}
        onClick={() => (open ? close(false) : setOpen(true))}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`${t("workspace.currentLayout")}: ${currentLabel}`}
        title={`${t("workspace.currentLayout")} · ${currentLabel}`}
      >
        <LayoutThumbnail tree={tree} />
        <span className="workspace-layout-caret" aria-hidden="true"><Icon name="chevron-down" size={12} /></span>
      </button>

      {open && (
        <div
          ref={panelRef}
          className="workspace-layout-popover"
          role="dialog"
          aria-label={t("workspace.currentLayout")}
        >
          <div className="workspace-layout-popover-head">
            <span>{t("workspace.currentLayout")}</span>
            <span className="workspace-panel-count-pill">{t("workspace.chartCountPill", { count: cellCount })}</span>
          </div>
          {locked && <p className="workspace-layout-popover-hint">{t("workspace.layoutLockedHint")}</p>}
          <div className="workspace-layout-grid" onKeyDown={handleGridKeyDown}>
            {templates.map((template) => {
              const active = layout === template.id;
              return (
                <button
                  key={template.id}
                  type="button"
                  className={active ? "active" : ""}
                  aria-pressed={active}
                  disabled={!ready || locked}
                  title={chartWorkspaceLayoutLabel(template.id)}
                  aria-label={chartWorkspaceLayoutLabel(template.id)}
                  onClick={() => {
                    if (!active) onSelectLayout(template.id);
                    close(true);
                  }}
                >
                  <LayoutThumbnail tree={template.tree} />
                  <span>{chartWorkspaceTemplateCellCount(template.id)}</span>
                </button>
              );
            })}
          </div>
          <button
            type="button"
            className="workspace-layout-manage"
            onClick={() => {
              close(false);
              onOpenManager();
            }}
          >
            {t("workspace.manage")}
            <span aria-hidden="true">→</span>
          </button>
        </div>
      )}
    </div>
  );
}

export default memo(WorkspaceLayoutPicker);
