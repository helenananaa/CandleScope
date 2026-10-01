import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import { strategyDockHeight } from "./strategyDockModel.js";

function load(scope: string) {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(`candlescope.strategy-dock.v1.${scope}`) ?? "null");
    const value = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
    return { height: typeof value.height === "number" && Number.isFinite(value.height) ? value.height : 280, collapsed: value.collapsed === true };
  } catch { return { height: 280, collapsed: false }; }
}

/** Owns layout only. Hidden content stays mounted so observing a run survives collapse. */
export default function StrategyDock({ scope, title, selector, children }: {
  scope: string; title: string; selector: ReactNode; children: ReactNode;
}) {
  useLocale();
  const root = useRef<HTMLElement>(null);
  const [preferences, setPreferences] = useState(() => load(scope));
  const [available, setAvailable] = useState(600);
  const [maximized, setMaximized] = useState(false);
  const drag = useRef<{ y: number; height: number } | null>(null);
  const height = preferences.collapsed ? 36 : strategyDockHeight(preferences.height, available, maximized);
  useLayoutEffect(() => {
    const workspace = root.current?.closest(".market-workspace-content");
    if (!workspace) return;
    const measure = () => setAvailable(workspace.getBoundingClientRect().height);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(workspace);
    return () => observer.disconnect();
  }, []);
  useLayoutEffect(() => {
    try { localStorage.setItem(`candlescope.strategy-dock.v1.${scope}`, JSON.stringify(preferences)); } catch { /* Best effort. */ }
  }, [scope, preferences]);
  const resize = (value: number) => {
    setMaximized(false);
    setPreferences({ height: strategyDockHeight(value, available), collapsed: false });
  };
  const collapse = () => { setMaximized(false); setPreferences((value) => ({ ...value, collapsed: !value.collapsed })); };
  return <section ref={root} className="strategy-dock" data-collapsed={preferences.collapsed} data-maximized={maximized} data-compact={height < 260}
    style={{ height, flexBasis: height }} aria-label={t("chartTester.title")}>
    <div className="strategy-dock-divider" role="separator" tabIndex={0} aria-orientation="horizontal"
      aria-label={t("chartTester.resize")} aria-valuemin={36} aria-valuemax={Math.round(available)} aria-valuenow={height}
      onDoubleClick={() => { setMaximized(false); setPreferences({ height: 280, collapsed: false }); }}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        drag.current = { y: event.clientY, height };
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={(event) => { if (drag.current) resize(drag.current.height + drag.current.y - event.clientY); }}
      onPointerUp={(event) => { drag.current = null; event.currentTarget.releasePointerCapture(event.pointerId); }}
      onPointerCancel={() => { drag.current = null; }} onLostPointerCapture={() => { drag.current = null; }}
      onKeyDown={(event) => {
        if (!["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        resize(event.key === "Home" ? 260 : event.key === "End" ? available : height + (event.key === "ArrowUp" ? 16 : -16));
      }} />
    <header className="strategy-dock-bar">
      <button className="strategy-dock-title" onClick={collapse} aria-expanded={!preferences.collapsed}>{t("chartTester.title")}</button>
      <span className="strategy-dock-context" title={title}>{title}</span>
      <div className="strategy-dock-selector">{selector}</div>
      <button onClick={collapse} aria-label={t(preferences.collapsed ? "pane.expand" : "pane.collapse")}>{t(preferences.collapsed ? "pane.expand" : "pane.collapse")}</button>
      <button aria-pressed={maximized} onClick={() => { setPreferences((value) => ({ ...value, collapsed: false })); setMaximized(!maximized); }}
        aria-label={t(maximized ? "strategyDock.restore" : "strategyDock.maximize")}>{t(maximized ? "strategyDock.restore" : "strategyDock.maximize")}</button>
    </header>
    <div className="strategy-dock-content" hidden={preferences.collapsed}>{children}</div>
  </section>;
}
