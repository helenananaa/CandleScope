import { useCallback, useEffect, useRef, useState } from "react";
import { t } from "../../../i18n/index.js";
import { Icon } from "../../../components/icons/Icon.js";
import { Button, Input, MenuItemButton, moveMenuFocus, useAnchoredPopup } from "../../../components/ui/index.js";

export interface StrategySwitcherItem {
  id: string;
  name: string;
  meta: string;
  running?: boolean;
}

export interface StrategySwitcherAction {
  id: string;
  label: string;
  onSelect(): void;
  disabled?: boolean;
  title?: string;
}

/** Names the strategy on this chart and is the only place to pick, add or manage strategies. */
export function StrategySwitcher({ items, activeId, actions, onSelect, renaming = false, onRename }: {
  items: readonly StrategySwitcherItem[];
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
    <Button ref={trigger} variant="ghost" className="strategy-switcher-trigger" aria-haspopup="menu" aria-expanded={open}
      aria-label={t("strategyCollection.select")} title={current?.name} onClick={() => setOpen(!open)}>
      <i className="strategy-status-dot" data-running={current?.running === true} aria-hidden="true" />
      <strong>{current?.name ?? t("strategyCollection.default")}</strong>
      {current?.meta && <small>{current.meta}</small>}
      <Icon name="chevron-down" size={12} />
    </Button>
    {open && <div ref={menu} className="strategy-switcher-menu" role="menu" aria-label={t("strategyCollection.list")}
      onKeyDown={(event) => {
        if (event.key === "Tab") { event.preventDefault(); setOpen(false); return; }
        moveMenuFocus(event, menu.current);
      }}>
      <p className="strategy-switcher-heading">{t("strategyCollection.list")}</p>
      {items.map((item) => <MenuItemButton key={item.id} ref={item.id === activeId ? chosen : undefined} role="menuitemradio" aria-checked={item.id === activeId}
        icon={<i className="strategy-status-dot" data-running={item.running === true} />}
        hint={item.id === activeId ? <Icon name="check" size={13} /> : undefined}
        onClick={() => choose(() => onSelect(item.id))}>
        <strong>{item.name}</strong>{item.meta && <small>{item.meta}</small>}
      </MenuItemButton>)}
      {actions.length > 0 && <hr />}
      {actions.map((action) => <MenuItemButton key={action.id} role="menuitem" disabled={action.disabled} title={action.title}
        onClick={() => choose(action.onSelect)}>
        {action.label}
      </MenuItemButton>)}
    </div>}
  </div>;
}
