import { useEffect, useId, useRef, useState } from "react";
import { useDrawingSurfacePlacement } from "./useDrawingEditorLayout.js";
import { t } from "../../i18n/index.js";

const colors = ["#e2e8f0", "#64748b", "#ef4444", "#f97316", "#f59e0b", "#eab308", "#22c55e", "#14b8a6", "#06b6d4", "#3b82f6", "#8b5cf6", "#ec4899"];
// Session-only convenience; the drawing document remains the style authority.
let recentColors: string[] = [];
function rememberColor(value: string): string[] {
  recentColors = [value, ...recentColors.filter((item) => item.toLowerCase() !== value.toLowerCase())].slice(0, 6);
  return recentColors;
}

export function StyleIcon({ name }: { name: "settings" | "delete" | "close" | "drag" | "lock" | "unlock" }) {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {name === "drag" ? <><circle cx="9" cy="5" r="1" /><circle cx="15" cy="5" r="1" /><circle cx="9" cy="12" r="1" /><circle cx="15" cy="12" r="1" /><circle cx="9" cy="19" r="1" /><circle cx="15" cy="19" r="1" /></> : name === "delete" ? <><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7" /></>
      : name === "lock" || name === "unlock" ? <><rect x="5" y="10" width="14" height="11" rx="2" /><path d={name === "lock" ? "M8 10V6a4 4 0 0 1 8 0v4" : "M8 10V6a4 4 0 0 1 8 0"} /><path d="M12 14v3" /></>
      : name === "close" ? <path d="m6 6 12 12M6 18 18 6" />
      : <><path d="M4 7h7m4 0h5M4 17h3m4 0h9" /><circle cx="13" cy="7" r="2" /><circle cx="9" cy="17" r="2" /></>}
  </svg>;
}

/** Native top-layer popover avoids clipping inside charts and scrolling property panels. */
export function ColorControl({ color, label, onCommit }: { color: string; label: string; onCommit(value: string): void }) {
  const trigger = useRef<HTMLButtonElement>(null);
  const popup = useRef<HTMLDivElement>(null);
  const id = useId();
  const [open, setOpen] = useState(false);
  const cancelled = useRef(false);
  const popupStyle = useDrawingSurfacePlacement(popup, trigger, open);
  const [hex, setHex] = useState(color);
  const [recent, setRecent] = useState(recentColors);
  useEffect(() => setHex(color), [color]);
  const choose = (value: string) => {
    if (/^#[0-9a-f]{6}$/i.test(value)) {
      onCommit(value);
      setHex(value);
      setRecent(rememberColor(value));
    }
    else setHex(color);
  };
  const dismiss = () => { popup.current?.hidePopover(); trigger.current?.focus(); };
  const commitHex = () => { if (!cancelled.current) choose(hex); cancelled.current = false; };
  return <div className="drawing-color-control">
    <button ref={trigger} type="button" popoverTarget={id} aria-expanded={open} aria-label={label} title={label}><span className="drawing-color-swatch" style={{ backgroundColor: color }} /><span className="drawing-chevron" aria-hidden="true">⌄</span></button>
    <div id={id} ref={popup} popover="auto" style={popupStyle} className="drawing-color-popover" role="group" aria-label={label}
      onToggle={(event) => { const visible = event.newState === "open"; setOpen(visible); if (visible) setRecent(recentColors); }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault(); event.stopPropagation(); cancelled.current = true; setHex(color); dismiss();
        }
      }}>
      <span className="drawing-control-caption">{label}</span>
      <div className="drawing-color-grid">{colors.map((value) => <button key={value} type="button" aria-label={`${label} ${value}`} aria-pressed={value.toLowerCase() === color.toLowerCase()} style={{ backgroundColor: value }} onClick={() => {
        choose(value); dismiss();
      }} />)}</div>
      {recent.length > 0 && <><span className="drawing-control-caption">{t("search.recent")}</span><div className="drawing-color-grid">{recent.map((value) => <button key={value} type="button" aria-label={`${t("search.recent")} ${value}`} style={{ backgroundColor: value }} onClick={() => {
        choose(value); dismiss();
      }} />)}</div></>}
      <div className="drawing-color-custom">
        <input aria-label={label} type="color" value={/^#[0-9a-f]{6}$/i.test(hex) ? hex : color} onChange={(event) => setHex(event.target.value)} onBlur={commitHex} onFocus={() => { cancelled.current = false; }} />
        <input aria-label={`${label} HEX`} value={hex} maxLength={7} spellCheck={false} onChange={(event) => setHex(event.target.value)} onBlur={commitHex} onFocus={() => { cancelled.current = false; }} onKeyDown={(event) => {
          if (event.key === "Enter") { event.preventDefault(); choose(hex); dismiss(); }
        }} />
      </div>
    </div>
  </div>;
}

export function WidthControl({ value, onCommit }: { value: number; onCommit(value: number): void }) {
  return <label className="drawing-width-control" title={t("drawing.settings.lineWidth", { size: value })}>
    <span className="drawing-line-sample" style={{ borderTopWidth: value }} aria-hidden="true" />
    <select aria-label={t("drawing.settings.lineWidth", { size: value })} value={value} onChange={(event) => onCommit(Number(event.target.value))}>
      {Array.from({ length: 10 }, (_, index) => index + 1).map((width) => <option key={width} value={width}>{width} px</option>)}
    </select>
  </label>;
}

export function LineStyleControl({ value, onCommit }: { value: "solid" | "dashed" | "dotted"; onCommit(value: "solid" | "dashed" | "dotted"): void }) {
  return <div className="drawing-line-options" role="group" aria-label={t("drawing.settings.lineStyle")}>
    {(["solid", "dashed", "dotted"] as const).map((style) => <button key={style} type="button" title={t(`drawing.settings.${style}`)} aria-label={t(`drawing.settings.${style}`)} aria-pressed={value === style} onClick={() => onCommit(style)}><span className="drawing-line-sample" style={{ borderTopStyle: style }} /></button>)}
  </div>;
}
