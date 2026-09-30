import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import type { DrawingChartAdapter } from "./drawingTypes.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";

let owner: string | null = null;
function claim(scope: string) { owner = scope; }
function release(scope: string) { if (owner === scope) owner = null; }

export default function DrawingHistoryBar({ container, adapter, scope, canUndo, canRedo, replay }: {
  adapter: DrawingChartAdapter | null;
  scope: string;
  container: RefObject<HTMLElement | null>;
  canUndo: boolean;
  canRedo: boolean;
  replay(direction: "undo" | "redo"): boolean;
}) {
  useLocale();
  const bar = useRef<HTMLDivElement>(null);
  const [top, setTop] = useState(8);
  useLayoutEffect(() => {
    const place = () => setTop((adapter?.getDrawingPanePlotRect?.()?.y ?? 0) + 8);
    place();
    return adapter?.subscribeDrawingFrameInvalidation?.(place);
  }, [adapter]);
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const activate = (event: PointerEvent) => {
      const rect = adapter?.getDrawingPanePlotRect?.();
      const parent = element.getBoundingClientRect();
      const y = event.clientY - parent.top;
      if (rect && y >= rect.y && y <= rect.y + rect.height) claim(scope);
    };
    element.addEventListener("pointerdown", activate, true);
    return () => { element.removeEventListener("pointerdown", activate, true); release(scope); };
  }, [container, adapter, scope]);
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const keydown = (event: KeyboardEvent) => {
      if (owner !== scope || event.defaultPrevented || event.altKey
        || !(event.ctrlKey || event.metaKey) || document.querySelector("dialog[open]")) return;
      const target = event.target;
      if (target instanceof HTMLElement && target !== document.body && !element.contains(target)
        && !bar.current?.contains(target)) return;
      if (target instanceof HTMLElement && target.closest('input, textarea, select, [contenteditable="true"]')) return;
      const key = event.key.toLowerCase();
      const direction = key === "z" ? (event.shiftKey ? "redo" : "undo") : key === "y" ? "redo" : null;
      if (direction && (direction === "undo" ? canUndo : canRedo) && replay(direction)) event.preventDefault();
    };
    document.addEventListener("keydown", keydown);
    return () => {
      document.removeEventListener("keydown", keydown);
    };
  }, [container, scope, canUndo, canRedo, replay]);
  if (!canUndo && !canRedo) return null;
  return <div ref={bar} className="drawing-history-bar" style={{ top }} onPointerDown={(event) => { claim(scope); event.stopPropagation(); }} onMouseDown={(event) => event.stopPropagation()} onClick={(event) => event.stopPropagation()}>
    <button type="button" aria-label={t("workspace.undo")} title={`${t("workspace.undo")} · Ctrl/⌘ Z`} disabled={!canUndo} onClick={() => replay("undo")}><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="m9 5-5 5 5 5M4 10h10a6 6 0 0 1 0 12" /></svg></button>
    <button type="button" aria-label={t("workspace.redo")} title={`${t("workspace.redo")} · Ctrl/⌘ Shift Z`} disabled={!canRedo} onClick={() => replay("redo")}><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="m15 5 5 5-5 5M20 10H10a6 6 0 0 0 0 12" /></svg></button>
  </div>;
}
