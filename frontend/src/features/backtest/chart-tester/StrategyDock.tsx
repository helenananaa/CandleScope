import { useCallback, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import { Icon } from "../../../components/icons/Icon.js";
import { strategyDockHeight } from "./strategyDockModel.js";
import { StrategyDockSlotsProvider, type StrategyDockSlotName, type StrategyDockSlotTargets } from "./StrategyDockSlots.js";

const BAR_HEIGHT = 41;

function load(scope: string) {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(`candlescope.strategy-dock.v1.${scope}`) ?? "null");
    const value = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
    return { height: typeof value.height === "number" && Number.isFinite(value.height) ? value.height : 280, collapsed: value.collapsed === true };
  } catch { return { height: 280, collapsed: false }; }
}

function assignSlot(name: StrategyDockSlotName, element: HTMLElement | null) {
  return (current: StrategyDockSlotTargets) => current[name] === element ? current : { ...current, [name]: element };
}

/**
 * One header row: which strategy, which view, what it did, and Run. Panes publish their
 * tabs, actions and notices into the header through StrategyDockSlot. Hidden content stays
 * mounted so observing a run survives collapse.
 */
export default function StrategyDock({ scope, identity, onClose, children }: {
  scope: string; identity: ReactNode; onClose?: () => void; children: ReactNode;
}) {
  useLocale();
  const root = useRef<HTMLElement>(null);
  const [preferences, setPreferences] = useState(() => load(scope));
  const [available, setAvailable] = useState(600);
  const [maximized, setMaximized] = useState(false);
  const [slots, setSlots] = useState<StrategyDockSlotTargets>({});
  const tabsRef = useCallback((element: HTMLElement | null) => setSlots(assignSlot("tabs", element)), []);
  const actionsRef = useCallback((element: HTMLElement | null) => setSlots(assignSlot("actions", element)), []);
  const noticeRef = useCallback((element: HTMLElement | null) => setSlots(assignSlot("notice", element)), []);
  const drag = useRef<{ y: number; height: number } | null>(null);
  const collapsed = preferences.collapsed;
  const height = collapsed ? BAR_HEIGHT : strategyDockHeight(preferences.height, available, maximized);
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
  const setCollapsed = (next: boolean) => { setMaximized(false); setPreferences((value) => ({ ...value, collapsed: next })); };
  return <section ref={root} className="strategy-dock" data-collapsed={collapsed} data-maximized={maximized} data-compact={height < 260}
    style={{ height, flexBasis: height }} aria-label={t("chartTester.title")}>
    <div className="strategy-dock-divider" role="separator" tabIndex={0} aria-orientation="horizontal"
      aria-label={t("chartTester.resize")} aria-valuemin={BAR_HEIGHT} aria-valuemax={Math.round(available)} aria-valuenow={height}
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
    <header className="strategy-dock-bar"
      onClickCapture={(event) => {
        // Choosing a view from the collapsed bar opens the dock on that view.
        if (collapsed && (event.target as Element).closest(".strategy-dock-tabs [role=tab]")) setCollapsed(false);
      }}
      onDoubleClick={(event) => { if (event.target === event.currentTarget) setCollapsed(!collapsed); }}>
      <div className="strategy-dock-identity">{identity}</div>
      <div className="strategy-dock-tabs" ref={tabsRef} />
      <div className="strategy-dock-actions" ref={actionsRef} />
      <div className="strategy-dock-window">
        <button type="button" className="strategy-dock-icon" aria-pressed={maximized}
          onClick={() => { setPreferences((value) => ({ ...value, collapsed: false })); setMaximized(!maximized); }}
          aria-label={t(maximized ? "strategyDock.restore" : "strategyDock.maximize")} title={t(maximized ? "strategyDock.restore" : "strategyDock.maximize")}>
          <Icon name={maximized ? "minimize" : "maximize"} size={14} />
        </button>
        <button type="button" className="strategy-dock-icon" aria-expanded={!collapsed} onClick={() => setCollapsed(!collapsed)}
          aria-label={t(collapsed ? "pane.expand" : "pane.collapse")} title={t(collapsed ? "pane.expand" : "pane.collapse")}>
          <Icon name={collapsed ? "chevron-up" : "chevron-down"} size={14} />
        </button>
        {onClose && <button type="button" className="strategy-dock-icon" onClick={onClose} aria-label={t("chartTester.close")} title={t("chartTester.close")}>
          <Icon name="close" size={14} />
        </button>}
      </div>
    </header>
    <div className="strategy-dock-notice" ref={noticeRef} hidden={collapsed} />
    <div className="strategy-dock-content" hidden={collapsed}>
      <StrategyDockSlotsProvider value={slots}>{children}</StrategyDockSlotsProvider>
    </div>
  </section>;
}
