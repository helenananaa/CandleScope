import DrawingVisibilityInputs from "../features/drawings/DrawingVisibilityInputs.js";
import { useRef, useState } from "react";
import { t } from "../i18n/index.js";
import { useLocale } from "../i18n/useLocale.js";
import type { TextDrawingPatch } from "../features/drawings/drawingTypes.js";
import type { SelectedTextSnapshot } from "../features/drawings/drawingSelectionController.js";
import { ColorControl, StyleIcon } from "../features/drawings/DrawingStyleInputs.js";
import { useDrawingSurfacePlacement, useDrawingToolbarPosition } from "../features/drawings/useDrawingEditorLayout.js";

export interface TextFormatBarProps {
  snapshot: SelectedTextSnapshot | null;
  onPatch(patch: TextDrawingPatch): void;
  onDelete?: () => void;
  onToggleLock?: () => void;
  currentInterval?: string;
}

function FontSize({ value, commit }: { value: number; commit(value: number): void }) {
  const [draft, setDraft] = useState(String(value));
  const cancelled = useRef(false);
  return <input className="drawing-font-size" aria-label={t("drawing.settings.fontSize")} type="number" min={8} max={200} value={draft}
    onChange={(event) => setDraft(event.target.value)}
    onBlur={() => {
      if (!cancelled.current && draft.trim() && Number.isFinite(Number(draft)) && Number(draft) >= 8 && Number(draft) <= 200) {
        if (Number(draft) !== value) commit(Number(draft));
      } else setDraft(String(value));
      cancelled.current = false;
    }}
    onKeyDown={(event) => {
      event.stopPropagation();
      if (event.key === "Enter") { event.preventDefault(); event.currentTarget.blur(); }
      if (event.key === "Escape") { event.preventDefault(); cancelled.current = true; event.currentTarget.blur(); }
    }} />;
}

export default function TextFormatBar({ snapshot, onPatch, onDelete, onToggleLock, currentInterval }: TextFormatBarProps) {
  useLocale();
  const toolbar = useDrawingToolbarPosition();
  const dialog = useRef<HTMLDialogElement>(null);
  const settings = useRef<HTMLButtonElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [draft, setDraft] = useState<TextDrawingPatch>({});
  const [resetRevision, setResetRevision] = useState(0);
  const placement = useDrawingSurfacePlacement(dialog, toolbar.root, expanded);
  if (!snapshot) return null;
  const value = { ...snapshot, ...draft };
  const patch = (next: TextDrawingPatch) => expanded ? setDraft((previous) => ({ ...previous, ...next })) : onPatch(next);
  const close = () => { setExpanded(false); setDraft({}); requestAnimationFrame(() => settings.current?.focus()); };
  const toggles = (["bold", "italic", "underline"] as const).map((field, index) => <button key={field} type="button" aria-label={t(`format.${field}`)} title={t(`format.${field}`)} aria-pressed={value[field]} onClick={() => patch({ [field]: !value[field] })}><span style={{ fontWeight: field === "bold" ? 700 : undefined, fontStyle: field === "italic" ? "italic" : undefined, textDecoration: field === "underline" ? "underline" : undefined }}>{["B", "I", "U"][index]}</span></button>);
  return <div ref={toolbar.root} className="selected-drawing-style-bar drawing-text-style-bar" style={toolbar.style}
    onPointerDown={(event) => event.stopPropagation()} onMouseDown={(event) => event.stopPropagation()} onClick={(event) => event.stopPropagation()} onDoubleClick={(event) => event.stopPropagation()} onWheel={(event) => event.stopPropagation()} onContextMenu={(event) => event.stopPropagation()}>
    <div className="selected-drawing-style-bar-main" inert={expanded}>
      <button type="button" className="drawing-toolbar-grip" aria-label={t("drawing.editor.moveToolbar")} {...toolbar.handle}><StyleIcon name="drag" /></button>
      <span className="drawing-object-name">{t("drawing.textNote")}</span>
      <ColorControl color={value.color} label={t("format.textColor")} onCommit={(color) => patch({ color })} />
      <FontSize key={value.fontSize} value={value.fontSize} commit={(fontSize) => patch({ fontSize })} />
      <div className="drawing-line-options">{toggles}</div>
      {onToggleLock && <button type="button" aria-label={t(snapshot.locked ? "drawing.editor.unlock" : "drawing.editor.lock")} title={t(snapshot.locked ? "drawing.editor.unlock" : "drawing.editor.lock")} aria-pressed={snapshot.locked === true} onClick={onToggleLock}><StyleIcon name={snapshot.locked ? "lock" : "unlock"} /></button>}
      <button ref={settings} type="button" aria-label={t("settings.title")} title={t("settings.title")} onClick={() => setExpanded(true)}><StyleIcon name="settings" /></button>
      <button type="button" className="drawing-delete-button" aria-label={t("format.delete")} title={t("format.delete")} onClick={onDelete}><StyleIcon name="delete" /></button>
    </div>
    {expanded && <dialog ref={dialog} style={placement} className="drawing-properties-panel" aria-label={t("drawing.textNote")} aria-modal="true" onCancel={(event) => { event.preventDefault(); close(); }} onKeyDown={(event) => event.stopPropagation()}>
      <header className="drawing-properties-header"><div><span className="drawing-control-caption">{t("settings.category.appearance")}</span><h3>{t("drawing.textNote")}</h3></div><button type="button" aria-label={t("settings.close")} onClick={close}><StyleIcon name="close" /></button></header>
      <div className="selected-drawing-style-bar-detail">
        {currentInterval && <DrawingVisibilityInputs value={value.visibleIntervals} currentInterval={currentInterval} onChange={visibleIntervals => patch({ visibleIntervals })} />}
        <div className="drawing-property-row"><span>{t("drawing.settings.fontSize")}</span><FontSize key={`${resetRevision}-${value.fontSize}`} value={value.fontSize} commit={(fontSize) => patch({ fontSize })} /></div>
        <div className="drawing-property-row"><span>{t("drawing.textNote")}</span><div className="drawing-line-options">{toggles}</div></div>
        <div className="drawing-property-row"><span>{t("format.textColor")}</span><ColorControl color={value.color} label={t("format.textColor")} onCommit={(color) => patch({ color })} /></div>
        <div className="drawing-property-row"><div className="drawing-line-options">{(["left", "center", "right"] as const).map((align) => <button key={align} type="button" aria-label={t("format.align", { id: align })} title={t("format.align", { id: align })} aria-pressed={value.align === align} onClick={() => patch({ align })}><svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5"><path d={`M2 4h16M${align === "right" ? 7 : align === "center" ? 4.5 : 2} 8h11M2 12h16M${align === "right" ? 7 : align === "center" ? 4.5 : 2} 16h11`} /></svg></button>)}</div></div>
        {(["bgColor", "borderColor"] as const).map((field) => <div className="drawing-property-row" key={field}><span>{t(field === "bgColor" ? "format.bgColor" : "format.borderColor")}</span><div className="drawing-line-options"><button type="button" aria-pressed={!value[field]} onClick={() => patch({ [field]: null })}>{t("format.none")}</button><ColorControl color={value[field] ?? "#64748b"} label={t(field === "bgColor" ? "format.bgColor" : "format.borderColor")} onCommit={(color) => patch({ [field]: color })} /></div></div>)}
      </div>
      <footer className="drawing-properties-footer"><button type="button" className="drawing-reset-button" title={t("drawing.editor.resetChangesHint")} onClick={() => { setDraft({}); setResetRevision((revision) => revision + 1); }}>{t("drawing.editor.resetChanges")}</button><button type="button" onClick={close}>{t("workspace.cancel")}</button><button type="button" className="drawing-save-button" disabled={value.visibleIntervals?.length === 0} onClick={() => { if (Object.keys(draft).length) onPatch(draft); close(); }}>{t("settings.saveAndClose")}</button></footer>
    </dialog>}
  </div>;
}
