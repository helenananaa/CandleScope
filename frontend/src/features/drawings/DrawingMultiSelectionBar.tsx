import type { SyntheticEvent } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { IconButton } from "../../components/ui/index.js";
import { StyleIcon } from "./DrawingStyleInputs.js";

export interface DrawingMultiSelectionActions {
  readonly count: number;
  readonly grouped: boolean;
  readonly canGroup: boolean;
  group(): boolean;
  ungroup(): boolean;
  copy(): number;
  duplicate(): boolean;
  deleteSelection(): boolean;
}

const icon = (path: string) => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={path} /></svg>;
const GROUP_ICON = icon("M4 4h6v6H4zM14 14h6v6h-6zM10 7h4a3 3 0 0 1 3 3v4M7 10v4a3 3 0 0 0 3 3h4");
const UNGROUP_ICON = icon("M4 4h6v6H4zM14 14h6v6h-6zM17 7l-3 3M7 17l3-3");
const COPY_ICON = icon("M9 9h11v11H9zM5 15H4V4h11v1");
const DUPLICATE_ICON = icon("M8 8h12v12H8zM4 16V4h12M14 11v6M11 14h6");

/** Shown instead of the one-drawing style bar while two or more drawings are selected. */
export default function DrawingMultiSelectionBar({ selection }: { selection: DrawingMultiSelectionActions }) {
  useLocale();
  const stop = (event: SyntheticEvent) => event.stopPropagation();
  const shortcut = (label: string, key: string) => `${label} · Ctrl/⌘ ${key}`;
  return <div
    className="selected-drawing-style-bar drawing-multi-selection-bar"
    role="group"
    aria-label={t("drawing.multi.label")}
    onPointerDown={stop}
    onMouseDown={stop}
    onMouseUp={stop}
    onClick={stop}
    onDoubleClick={stop}
    onWheel={stop}
    onContextMenu={stop}
  >
    <div className="selected-drawing-style-bar-main">
      <strong aria-live="polite">{t("drawing.multi.selected", { count: String(selection.count) })}</strong>
      <span className="drawing-toolbar-divider" />
      {selection.grouped
        ? <IconButton label={shortcut(t("drawing.multi.ungroup"), "Shift G")} icon={UNGROUP_ICON} onClick={() => selection.ungroup()} />
        : <IconButton label={selection.canGroup ? shortcut(t("drawing.multi.group"), "G") : t("drawing.multi.groupUnavailable")}
          icon={GROUP_ICON} disabled={!selection.canGroup} onClick={() => selection.group()} />}
      <IconButton label={shortcut(t("drawing.multi.copy"), "C")} icon={COPY_ICON} onClick={() => selection.copy()} />
      <IconButton label={shortcut(t("drawing.multi.duplicate"), "D")} icon={DUPLICATE_ICON} onClick={() => selection.duplicate()} />
      <span className="drawing-toolbar-divider" />
      <IconButton variant="danger" label={t("drawing.multi.delete")} icon={<StyleIcon name="delete" />} onClick={() => selection.deleteSelection()} />
    </div>
  </div>;
}
