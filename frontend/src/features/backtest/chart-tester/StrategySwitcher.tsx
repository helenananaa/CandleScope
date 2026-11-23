import { useCallback, useEffect, useRef, useState } from "react";
import { t } from "../../../i18n/index.js";
import { Icon } from "../../../components/icons/Icon.js";
import { Input, moveMenuFocus, useAnchoredPopup } from "../../../components/ui/index.js";

export interface StrategySwitcherItem {
  id: string;
  name: string;
  meta: string;
  running?: boolean;
}

/** A retired Pyne strategy from a build before PR #105: shown, never selectable or runnable. */
export interface RetiredStrategySwitcherItem {
  id: string;
  name: string;
  /** Without it the entry is listed only. */
  onRemove?(): void;
}

export interface StrategySwitcherAction {
  id: string;
  label: string;
  onSelect(): void;
  disabled?: boolean;
  title?: string;
}

/** The menu's retired Pyne entries: a name and a Retired label, never a strategy to pick or run. */
export function RetiredStrategySwitcherSection({ items, onRemove }: {
  items: readonly RetiredStrategySwitcherItem[];
  onRemove(item: RetiredStrategySwitcherItem): void;
}) {
  if (items.length === 0) return null;
  return <>
    <hr />
    <p className="strategy-switcher-heading">{t("strategyCollection.retiredBadge")}</p>
    {items.map((item) => <div key={item.id} className="strategy-switcher-retired" data-retired="true">
      <span><strong>{item.name}</strong><small>{t("strategyCollection.retiredBadge")}</small></span>
      {item.onRemove && <button type="button" role="menuitem" aria-label={t("strategyCollection.removeRetired", { name: item.name })}
        onClick={() => onRemove(item)}>
        <span>{t("strategyCollection.remove")}</span>
      </button>}
    </div>)}
    <p className="strategy-switcher-note">{t("strategyCollection.pyneRetired")}</p>
  </>;
}

/** Names the strategy on this chart and is the only place to pick, add or manage strategies. */
export function StrategySwitcher({ items, retired = [], activeId, actions, onSelect, renaming = false, onRename }: {
  items: readonly StrategySwitcherItem[];
  retired?: readonly RetiredStrategySwitcherItem[];
  activeId: string;
  actions: readonly StrategySwitcherAction[];
  onSelect(id: string): void;
  renaming?: boolean;
  onRename?(name: string | null): void;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const chosen = useRef<HTMLButtonElement>(null);
  const renameSettled = useRef(false);
  const current = items.find((item) => item.id === activeId) ?? items[0];
  const menuOpen = open && !renaming;
  const closeMenu = useCallback(() => setOpen(false), []);
  // Escape and Tab close it; focus starts on the strategy shown and goes back to the trigger.
  useAnchoredPopup({ open: menuOpen, onClose: closeMenu, popupRef: menu, triggerRef: trigger, initialFocusRef: chosen });
  useEffect(() => {
    if (!open) return undefined;
    const close = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);
  const choose = (run: () => void) => { setOpen(false); run(); };
  if (renaming && current && onRename) {
    const settle = (name: string | null) => { if (!renameSettled.current) { renameSettled.current = true; onRename(name); } };
    return <div className="strategy-switcher">
      <Input size="sm" className="strategy-switcher-rename" autoFocus maxLength={80} defaultValue={current.name}
        aria-label={t("strategyCollection.name")} placeholder={t("strategyCollection.default")}
        onFocus={() => { renameSettled.current = false; }}
        onBlur={(event) => settle(event.currentTarget.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") settle(event.currentTarget.value);
          if (event.key === "Escape") { event.stopPropagation(); settle(null); }
        }} />
    </div>;
  }
  return <div className="strategy-switcher" ref={root}>
    <button ref={trigger} type="button" className="strategy-switcher-trigger" aria-haspopup="menu" aria-expanded={open}
      aria-label={t("strategyCollection.select")} title={current?.name} onClick={() => setOpen(!open)}>
      <i className="strategy-status-dot" data-running={current?.running === true} aria-hidden="true" />
      <strong>{current?.name ?? t("strategyCollection.default")}</strong>
      {current?.meta && <small>{current.meta}</small>}
      <Icon name="chevron-down" size={12} />
    </button>
    {open && <div ref={menu} className="strategy-switcher-menu" role="menu" aria-label={t("strategyCollection.list")}
      onKeyDown={(event) => {
        if (event.key === "Tab") { event.preventDefault(); setOpen(false); return; }
        moveMenuFocus(event, menu.current);
      }}>
      <p className="strategy-switcher-heading">{t("strategyCollection.list")}</p>
      {items.map((item) => <button key={item.id} ref={item.id === activeId ? chosen : undefined} type="button" role="menuitemradio" aria-checked={item.id === activeId}
        onClick={() => choose(() => onSelect(item.id))}>
        <i className="strategy-status-dot" data-running={item.running === true} aria-hidden="true" />
        <span><strong>{item.name}</strong>{item.meta && <small>{item.meta}</small>}</span>
        {item.id === activeId && <Icon name="check" size={13} />}
      </button>)}
      <RetiredStrategySwitcherSection items={retired} onRemove={(item) => choose(() => item.onRemove?.())} />
      {actions.length > 0 && <hr />}
      {actions.map((action) => <button key={action.id} type="button" role="menuitem" disabled={action.disabled} title={action.title}
        onClick={() => choose(action.onSelect)}>
        <span>{action.label}</span>
      </button>)}
    </div>}
  </div>;
}
