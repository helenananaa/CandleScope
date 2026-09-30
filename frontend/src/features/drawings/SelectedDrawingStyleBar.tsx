import { drawingName } from "./drawingObjectLabels.js";
import DrawingVisibilityInputs from "./DrawingVisibilityInputs.js";
import { useEffect, useId, useRef, useState } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import type { DrawingStylePatch } from "./drawingInteractionController.js";
import type { SelectedDrawingMeta } from "./drawingSelectionController.js";

import { useDrawingToolbarPosition, useDrawingSurfacePlacement } from "./useDrawingEditorLayout.js";

import { ColorControl as CommitColorInput, WidthControl, LineStyleControl, StyleIcon } from "./DrawingStyleInputs.js";
import DrawingCoordinateInputs from "./DrawingCoordinateInputs.js";
import DrawingStyleTemplates from "./DrawingStyleTemplates.js";
import { coordinateDraft, parseCoordinateDraft, sameCoordinates, type CoordinateDraft, type DrawingCoordinate } from "./drawingProperties.js";

function CommitNumberInput({ value, min, max, step, onCommit }: {
  value: number;
  min: number;
  max?: number;
  step: number;
  onCommit(value: number): void;
}) {
  const [draft, setDraft] = useState(String(value));
  const cancelled = useRef(false);
  useEffect(() => { setDraft(String(value)); }, [value]);
  const commit = () => {
    if (cancelled.current) { cancelled.current = false; return; }
    const parsed = Number(draft);
    if (draft !== "" && Number.isFinite(parsed) && parsed >= min
      && (max === undefined || parsed <= max)) onCommit(parsed);
    else setDraft(String(value));
  };
  return <input type="number" min={min} max={max} step={step} value={draft}
    onChange={(event) => setDraft(event.target.value)}
    onBlur={commit}
    onKeyDown={(event) => {
      event.stopPropagation();
      if (event.key === "Enter") event.currentTarget.blur();
      if (event.key === "Escape") { event.preventDefault(); cancelled.current = true; setDraft(String(value)); event.currentTarget.blur(); }
    }} />;
}


type Props = {
  drawing: SelectedDrawingMeta;
  currentInterval?: string;
  onPatch(patch: DrawingStylePatch): void;
  onSave?(id: string, patch: DrawingStylePatch, coordinates?: readonly DrawingCoordinate[], expectedCoordinates?: readonly DrawingCoordinate[]): boolean;
  onDelete(): void;
  openRequestRevision?: number;
};

export default function SelectedDrawingStyleBar(props: Props) {
  return <DrawingStyleEditor key={props.drawing.id} {...props} />;
}

function DrawingStyleEditor({ drawing: selected, onPatch: commitPatch, onSave, onDelete, currentInterval, openRequestRevision = 0 }: Props) {
  useLocale();
  const editorId = useId();
  const [expanded, setExpanded] = useState(openRequestRevision > 0);
  const [patch, setPatch] = useState<DrawingStylePatch>({});
  const [newLevel, setNewLevel] = useState("");
  const [tab, setTab] = useState<"style" | "coordinates">("style");
  const [coordinateBase, setCoordinateBase] = useState(selected.coordinates);
  const [points, setPoints] = useState<CoordinateDraft[] | null>(() => selected.coordinates ? coordinateDraft(selected.coordinates) : null);
  const [saveFailed, setSaveFailed] = useState(false);
  const [resetRevision, setResetRevision] = useState(0);
  const canEditCoordinates = !!onSave && !!coordinateBase;
  const parsedPoints = canEditCoordinates && points ? parseCoordinateDraft(points, coordinateBase) : null;
  const invalidCoordinates = canEditCoordinates && parsedPoints === null;
  const coordinatesChanged = parsedPoints && coordinateBase && !sameCoordinates(parsedPoints, coordinateBase);
  const resetDraft = (keepTab = false) => {
    setPatch({}); setNewLevel(""); setSaveFailed(false);
    if (!keepTab) setTab("style");
    setResetRevision((revision) => revision + 1);
    setCoordinateBase(selected.coordinates);
    setPoints(selected.coordinates ? coordinateDraft(selected.coordinates) : null);
  };
  const drawing = { ...selected, ...patch };
  const onPatch = (next: DrawingStylePatch) => expanded ? setPatch((previous) => ({ ...previous, ...next })) : commitPatch(next);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const toolbar = useDrawingToolbarPosition();
  const panelStyle = useDrawingSurfacePlacement(dialogRef, toolbar.root, expanded);
  const settingsRef = useRef<HTMLButtonElement>(null);
  const close = () => {
    setExpanded(false);
    resetDraft();
    requestAnimationFrame(() => settingsRef.current?.focus());
  };
  useEffect(() => {
    if (expanded) dialogRef.current?.focus();
  }, [expanded]);
  useEffect(() => {
    if (openRequestRevision > 0) {
      setPatch({}); setNewLevel(""); setTab("style"); setSaveFailed(false);
      setCoordinateBase(selected.coordinates);
      setPoints(selected.coordinates ? coordinateDraft(selected.coordinates) : null);
      setExpanded(true);
    }
    // An explicit open request captures the current coordinates once, not on each selection refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openRequestRevision]);
  const isShape = drawing.type === "rectangle" || drawing.type === "ellipse" || drawing.type === "shape";
  const isFib = drawing.type === "fibonacci";
  const isPosition = drawing.type === "position" || drawing.type === "position-long" || drawing.type === "position-short";
  const hasStroke = typeof drawing.color === "string" && typeof drawing.lineWidth === "number";
  const invalidLevel = newLevel.trim() !== "" && (!Number.isFinite(Number(newLevel))
    || (drawing.levels ?? []).length >= 32
    || (drawing.levels ?? []).some((item) => Math.abs(item.level - Number(newLevel)) < 0.0001));
  const addFibLevel = () => {
    const level = Number(newLevel);
    const levels = drawing.levels ?? [];
    if (newLevel.trim() === "" || !Number.isFinite(level) || levels.length >= 32
      || levels.some((item) => Math.abs(item.level - level) < 0.0001)) return;
    onPatch({ levels: [...levels, { level, color: drawing.color ?? "#f59e0b", enabled: true }]
      .sort((left, right) => left.level - right.level) });
    setNewLevel("");
  };
  const stop = (event: React.SyntheticEvent) => event.stopPropagation();
  return <div
    className="selected-drawing-style-bar"
    ref={toolbar.root}
    style={toolbar.style}
    role="group"
    aria-label={t("drawing.settings.selectedObject", { name: drawingName(drawing.type) })}
    data-selected-drawing-id={drawing.id}
    onPointerDown={stop}
    onMouseDown={stop}
    onMouseUp={stop}
    onClick={stop}
    onDoubleClick={stop}
    onWheel={stop}
    onContextMenu={stop}
    onKeyDown={stop}
  >
    <div className="selected-drawing-style-bar-main" inert={expanded}>
      <button type="button" className="drawing-drag-handle" aria-label={t("drawing.editor.moveToolbar")} title={t("drawing.editor.moveToolbar")} {...toolbar.handle}><StyleIcon name="drag" /></button>
      <strong>{drawingName(drawing.type)}</strong>
      {hasStroke && <>
        <CommitColorInput
          key={`${drawing.id}-stroke`}
          color={drawing.color ?? "#f59e0b"}
          label={t("drawing.settings.lineColor")}
          onCommit={(color) => onPatch({ color })}
        />
        <WidthControl value={drawing.lineWidth ?? 2} onCommit={(lineWidth) => onPatch({ lineWidth })} />
      </>}
      {isShape && <LineStyleControl value={drawing.lineStyle ?? "solid"} onCommit={(lineStyle) => onPatch({ lineStyle })} />}
      <span className="drawing-toolbar-divider" />
      {onSave && <button type="button" aria-label={t(selected.locked ? "drawing.editor.unlock" : "drawing.editor.lock")} title={t(selected.locked ? "drawing.editor.unlock" : "drawing.editor.lock")} aria-pressed={selected.locked === true}
        onClick={() => commitPatch({ locked: !selected.locked })}><StyleIcon name={selected.locked ? "lock" : "unlock"} /></button>}
      <button ref={settingsRef} type="button" aria-label={t("drawing.settings.more")}
        title={t("drawing.settings.more")} aria-haspopup="dialog"
        aria-expanded={expanded} onClick={() => { resetDraft(); setExpanded(!expanded); }}><StyleIcon name="settings" /></button>
      <button className="drawing-delete-button" type="button" aria-label={t("format.delete")}
        title={t("format.delete")} onClick={onDelete}><StyleIcon name="delete" /></button>
    </div>
    {expanded && <dialog className="drawing-properties-panel" style={panelStyle} role="dialog" aria-modal="true" aria-label={t("drawing.settings.selectedObject", { name: drawingName(drawing.type) })} ref={dialogRef} tabIndex={-1}
      onCancel={(event) => { event.preventDefault(); close(); }}
      onKeyDown={(event) => event.stopPropagation()}>
      <header className="drawing-properties-header"><div><span className="drawing-control-caption">{t("settings.category.appearance")}</span><h3>{drawingName(drawing.type)}</h3></div>
        <button type="button" aria-label={t("settings.close")} onClick={close}><StyleIcon name="close" /></button>
      </header>
      {canEditCoordinates && <div className="drawing-properties-tabs" role="tablist" aria-label={t("drawing.settings.more")}>
        {(["style", "coordinates"] as const).map((name) => <button key={name} id={`${editorId}-tab-${name}`} type="button" role="tab"
          aria-selected={tab === name} aria-controls={`${editorId}-panel-${name}`} tabIndex={tab === name ? 0 : -1}
          onKeyDown={(event) => {
            if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
              event.preventDefault();
              const next = event.key === "Home" ? "style" : event.key === "End" ? "coordinates" : tab === "style" ? "coordinates" : "style";
              setTab(next);
              const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]');
              buttons?.[next === "style" ? 0 : 1]?.focus();
            }
          }} onClick={() => setTab(name)}>{t(name === "style" ? "drawing.editor.style" : "drawing.editor.coordinates")}</button>)}
      </div>}
      <div className="selected-drawing-style-bar-detail">
      <div id={`${editorId}-panel-style`} role={canEditCoordinates ? "tabpanel" : undefined} aria-labelledby={canEditCoordinates ? `${editorId}-tab-style` : undefined} hidden={tab !== "style"} className="drawing-style-fields">
      <DrawingStyleTemplates drawing={drawing} onApply={onPatch} />
      {currentInterval && onSave && <DrawingVisibilityInputs value={drawing.visibleIntervals} currentInterval={currentInterval} onChange={visibleIntervals => onPatch({ visibleIntervals })} />}
      {hasStroke && <div className="drawing-property-row"><span>{t("drawing.settings.lineColor")}</span><CommitColorInput color={drawing.color ?? "#f59e0b"} label={t("drawing.settings.lineColor")} onCommit={(color) => onPatch({ color })} /></div>}
      {hasStroke && <label>{t("drawing.settings.lineWidth", { size: drawing.lineWidth ?? 2 })}
        <CommitNumberInput key={resetRevision} value={drawing.lineWidth ?? 2} min={1} max={10} step={1}
          onCommit={(lineWidth) => onPatch({ lineWidth })} />
      </label>}
      {isShape && <>
        <div className="drawing-property-row"><span>{t("drawing.settings.fillColor")}</span>
          <CommitColorInput
            key={`${drawing.id}-fill`}
            color={drawing.fillColor ?? drawing.color ?? "#f59e0b"}
            label={t("drawing.settings.fillColor")}
            onCommit={(fillColor) => onPatch({ fillColor })}
          />
        </div>
        <label>{t("drawing.editor.opacity")}
          <input type="range" min="0" max="100" step="1"
            value={Math.round((drawing.fillOpacity ?? 0) * 100)}
            onChange={(event) => onPatch({ fillOpacity: Number(event.target.value) / 100 })} />
          <output>{Math.round((drawing.fillOpacity ?? 0) * 100)}%</output>
        </label>
        <div className="drawing-property-row"><span>{t("drawing.settings.lineStyle")}</span><LineStyleControl value={drawing.lineStyle ?? "solid"} onCommit={(lineStyle) => onPatch({ lineStyle })} /></div>
      </>}
      {drawing.type === "highlighter" && <label>{t("drawing.editor.opacity")}
        <input type="range" min="5" max="100" step="5"
          value={Math.round((drawing.opacity ?? 0.35) * 100)}
          onChange={(event) => onPatch({ opacity: Number(event.target.value) / 100 })} />
        <output>{Math.round((drawing.opacity ?? 0.35) * 100)}%</output>
      </label>}
      {isFib && <div className="selected-drawing-fib-levels">
        <span>{t("drawing.settings.fibonacciLevels")}</span>
        {(drawing.levels ?? []).map((level, index) => <div className="drawing-fib-row" key={`${index}-${level.level}`}>
          <input type="checkbox" checked={level.enabled}
            aria-label={String(level.level)}
            onChange={(event) => onPatch({ levels: (drawing.levels ?? []).map((item, itemIndex) =>
              itemIndex === index ? { ...item, enabled: event.target.checked } : item) })} />
          <span>{level.level}</span>
          <CommitColorInput color={level.color} label={String(level.level)}
            onCommit={(color) => onPatch({ levels: (drawing.levels ?? []).map((item, itemIndex) =>
              itemIndex === index ? { ...item, color } : item) })} />
          <button type="button" title={t("drawing.settings.removeLevel")}
            aria-label={t("drawing.settings.removeLevel")}
            onClick={() => onPatch({ levels: (drawing.levels ?? []).filter((_, itemIndex) => itemIndex !== index) })}><StyleIcon name="delete" /></button>
        </div>)}
        <div className="drawing-fib-add">
          <input type="number" value={newLevel} step="any" aria-invalid={invalidLevel} aria-label={t("drawing.settings.addLevelPlaceholder")}
            placeholder={t("drawing.settings.addLevelPlaceholder")}
            onChange={(event) => setNewLevel(event.target.value)}
            onKeyDown={(event) => {
              event.stopPropagation();
              if (event.key === "Enter") addFibLevel();
            }} />
          <button type="button" aria-label={t("drawing.settings.addLevelPlaceholder")} disabled={!newLevel.trim() || invalidLevel}
            onClick={addFibLevel}>+</button>
        </div>
        {invalidLevel && <p className="drawing-field-error" role="status">{t("drawing.editor.invalidLevel")}</p>}
      </div>}
      {isPosition && <label>{t("drawing.settings.positionSize")}
        <CommitNumberInput key={resetRevision} value={drawing.positionSize ?? 1000} min={1} step={100}
          onCommit={(positionSize) => onPatch({ positionSize })} />
      </label>}
      </div>
      {canEditCoordinates && points && <div id={`${editorId}-panel-coordinates`} role="tabpanel" aria-labelledby={`${editorId}-tab-coordinates`} hidden={tab !== "coordinates"}>
        {selected.locked && <p className="drawing-control-caption" role="status">{t("drawing.editor.lockedHint")}</p>}
        <DrawingCoordinateInputs disabled={selected.locked === true} draft={points} onChange={(next) => { setPoints(next); setSaveFailed(false); }} />
      </div>}
      {invalidCoordinates && <p className="drawing-field-error" role="status">{t("drawing.editor.invalidCoordinates")}</p>}
      {saveFailed && <p className="drawing-field-error" role="alert">{t("drawing.editor.saveFailed")}</p>}
      </div>
      <footer className="drawing-properties-footer">
        <button type="button" className="drawing-reset-button" title={t("drawing.editor.resetChangesHint")} onClick={() => resetDraft(true)}>{t("drawing.editor.resetChanges")}</button>
        <button type="button" onClick={close}>{t("workspace.cancel")}</button>
        <button type="button" className="drawing-save-button" disabled={invalidCoordinates || drawing.visibleIntervals?.length === 0} onClick={() => {
          if (Object.keys(patch).length || coordinatesChanged) {
            if (onSave) {
              if (!onSave(selected.id, patch, coordinatesChanged ? parsedPoints ?? undefined : undefined, coordinateBase)) { setSaveFailed(true); return; }
            } else commitPatch(patch);
          }
          close();
        }}>{t("settings.saveAndClose")}</button>
      </footer>
    </dialog>}
  </div>;
}
