import { useEffect, useRef, useState } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import type { DrawingStylePatch } from "./drawingInteractionController.js";
import type { SelectedDrawingMeta } from "./drawingSelectionController.js";

const colorPattern = /^#[0-9a-f]{6}$/i;

function CommitColorInput({ color, label, onCommit }: {
  color: string;
  label: string;
  onCommit(color: string): void;
}) {
  const [draft, setDraft] = useState(color);
  const commitRef = useRef(onCommit);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => { commitRef.current = onCommit; }, [onCommit]);
  useEffect(() => { setDraft(color); }, [color]);
  useEffect(() => () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
  }, []);
  const commit = (value: string) => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = null;
    if (colorPattern.test(value) && value !== color) commitRef.current(value);
  };
  return <input
    type="color"
    aria-label={label}
    title={label}
    value={draft}
    onChange={(event) => {
      const value = event.target.value;
      setDraft(value);
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      timeoutRef.current = setTimeout(() => commitRef.current(value), 350);
    }}
    onBlur={() => commit(draft)}
  />;
}

function CommitNumberInput({ value, min, max, step, onCommit }: {
  value: number;
  min: number;
  max?: number;
  step: number;
  onCommit(value: number): void;
}) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => { setDraft(String(value)); }, [value]);
  const commit = () => {
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
      if (event.key === "Escape") { setDraft(String(value)); event.currentTarget.blur(); }
    }} />;
}

function drawingName(type: string): string {
  if (type === "fibonacci") return t("drawing.settings.fibonacciLevels");
  if (type === "position") return t("drawing.settings.position");
  const key = ({
    line: "drawing.variant.line-segment",
    "line-segment": "drawing.variant.line-segment",
    "line-ray": "drawing.variant.line-ray",
    "line-infinite": "drawing.variant.line-infinite",
    "horizontal-line": "drawing.variant.line-horizontal",
    "vertical-line": "drawing.variant.line-vertical",
    "cross-line": "drawing.variant.line-cross",
    "angle-measure": "drawing.variant.angle-measure",
    rectangle: "drawing.variant.shape-rectangle",
    ellipse: "drawing.variant.shape-ellipse",
    freehand: "drawing.variant.pen",
    highlighter: "drawing.variant.highlighter",
    "position-long": "drawing.variant.position-long",
    "position-short": "drawing.variant.position-short",
  } as const)[type as "line"];
  return key ? t(key) : type;
}

export default function SelectedDrawingStyleBar({ drawing, onPatch, onDelete, openRequestRevision = 0 }: {
  drawing: SelectedDrawingMeta;
  onPatch(patch: DrawingStylePatch): void;
  onDelete(): void;
  openRequestRevision?: number;
}) {
  useLocale();
  const [expanded, setExpanded] = useState(openRequestRevision > 0);
  const [newLevel, setNewLevel] = useState("");
  useEffect(() => { setExpanded(false); }, [drawing.id]);
  useEffect(() => {
    if (openRequestRevision > 0) setExpanded(true);
  }, [openRequestRevision]);
  const isShape = drawing.type === "rectangle" || drawing.type === "ellipse" || drawing.type === "shape";
  const isFib = drawing.type === "fibonacci";
  const isPosition = drawing.type === "position" || drawing.type === "position-long" || drawing.type === "position-short";
  const hasStroke = typeof drawing.color === "string" && typeof drawing.lineWidth === "number";
  const addFibLevel = () => {
    const level = Number(newLevel);
    const levels = drawing.levels ?? [];
    if (newLevel === "" || !Number.isFinite(level) || levels.length >= 32
      || levels.some((item) => Math.abs(item.level - level) < 0.0001)) return;
    onPatch({ levels: [...levels, { level, color: drawing.color ?? "#f59e0b", enabled: true }]
      .sort((left, right) => left.level - right.level) });
    setNewLevel("");
  };
  const stop = (event: React.SyntheticEvent) => event.stopPropagation();
  return <div
    className="selected-drawing-style-bar"
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
  >
    <div className="selected-drawing-style-bar-main">
      <strong>{drawingName(drawing.type)}</strong>
      {hasStroke && <>
        <CommitColorInput
          key={`${drawing.id}-stroke`}
          color={drawing.color ?? "#f59e0b"}
          label={t("drawing.settings.lineColor")}
          onCommit={(color) => onPatch({ color })}
        />
        <input
          type="range" min="1" max="10" step="1"
          value={drawing.lineWidth ?? 2}
          aria-label={t("drawing.settings.lineWidth", { size: drawing.lineWidth ?? 2 })}
          title={t("drawing.settings.lineWidth", { size: drawing.lineWidth ?? 2 })}
          onChange={(event) => onPatch({ lineWidth: Number(event.target.value) })}
        />
      </>}
      <button type="button" aria-label={t("drawing.settings.more")}
        title={t("drawing.settings.more")}
        aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>⚙</button>
      <button type="button" aria-label={t("format.delete")}
        title={t("format.delete")} onClick={onDelete}>×</button>
    </div>
    {expanded && <div className="selected-drawing-style-bar-detail">
      {hasStroke && <label>{t("drawing.settings.lineWidth", { size: drawing.lineWidth ?? 2 })}
        <CommitNumberInput value={drawing.lineWidth ?? 2} min={1} max={10} step={1}
          onCommit={(lineWidth) => onPatch({ lineWidth })} />
      </label>}
      {isShape && <>
        <label>{t("drawing.settings.fillColor")}
          <CommitColorInput
            key={`${drawing.id}-fill`}
            color={drawing.fillColor ?? drawing.color ?? "#f59e0b"}
            label={t("drawing.settings.fillColor")}
            onCommit={(fillColor) => onPatch({ fillColor })}
          />
        </label>
        <label>{t("drawing.settings.opacity")}
          <input type="range" min="0" max="100" step="1"
            value={Math.round((drawing.fillOpacity ?? 0) * 100)}
            onChange={(event) => onPatch({ fillOpacity: Number(event.target.value) / 100 })} />
          <output>{Math.round((drawing.fillOpacity ?? 0) * 100)}%</output>
        </label>
        <label>{t("drawing.settings.lineStyle")}
          <select value={drawing.lineStyle ?? "solid"}
            onChange={(event) => onPatch({ lineStyle: event.target.value as "solid" | "dashed" | "dotted" })}>
            <option value="solid">{t("drawing.settings.solid")}</option>
            <option value="dashed">{t("drawing.settings.dashed")}</option>
            <option value="dotted">{t("drawing.settings.dotted")}</option>
          </select>
        </label>
      </>}
      {drawing.type === "highlighter" && <label>{t("drawing.settings.opacity")}
        <input type="range" min="5" max="100" step="5"
          value={Math.round((drawing.opacity ?? 0.35) * 100)}
          onChange={(event) => onPatch({ opacity: Number(event.target.value) / 100 })} />
        <output>{Math.round((drawing.opacity ?? 0.35) * 100)}%</output>
      </label>}
      {isFib && <div className="selected-drawing-fib-levels">
        <span>{t("drawing.settings.fibonacciLevels")}</span>
        {(drawing.levels ?? []).map((level, index) => <label key={`${index}-${level.level}`}>
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
            onClick={() => onPatch({ levels: (drawing.levels ?? []).filter((_, itemIndex) => itemIndex !== index) })}>×</button>
        </label>)}
        <label>
          <input type="number" value={newLevel} step="any"
            placeholder={t("drawing.settings.addLevelPlaceholder")}
            onChange={(event) => setNewLevel(event.target.value)}
            onKeyDown={(event) => {
              event.stopPropagation();
              if (event.key === "Enter") addFibLevel();
            }} />
          <button type="button" aria-label={t("drawing.settings.addLevelPlaceholder")}
            onClick={addFibLevel}>+</button>
        </label>
      </div>}
      {isPosition && <label>{t("drawing.settings.positionSize")}
        <CommitNumberInput value={drawing.positionSize ?? 1000} min={1} step={100}
          onCommit={(positionSize) => onPatch({ positionSize })} />
      </label>}
    </div>}
  </div>;
}
