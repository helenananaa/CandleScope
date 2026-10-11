import { useEffect, useRef, useState } from "react";
import { t } from "../../../i18n/index.js";
import { Icon } from "../../../components/icons/Icon.js";

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
  const renameSettled = useRef(false);
  const current = items.find((item) => item.id === activeId) ?? items[0];
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
      <input className="strategy-switcher-rename" autoFocus maxLength={80} defaultValue={current.name}
        aria-label={t("strategyCollection.name")} placeholder={t("strategyCollection.default")}
        onFocus={() => { renameSettled.current = false; }}
        onBlur={(event) => settle(event.currentTarget.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") settle(event.currentTarget.value);
          if (event.key === "Escape") { event.stopPropagation(); settle(null); }
        }} />
    </div>;
  }
  return <div className="strategy-switcher" ref={root}
    onKeyDown={(event) => { if (event.key === "Escape" && open) { event.stopPropagation(); setOpen(false); } }}>
    <button type="button" className="strategy-switcher-trigger" aria-haspopup="menu" aria-expanded={open}
      aria-label={t("strategyCollection.select")} title={current?.name} onClick={() => setOpen(!open)}>
      <i className="strategy-status-dot" data-running={current?.running === true} aria-hidden="true" />
      <strong>{current?.name ?? t("strategyCollection.default")}</strong>
      {current?.meta && <small>{current.meta}</small>}
      <Icon name="chevron-down" size={12} />
    </button>
    {open && <div className="strategy-switcher-menu" role="menu" aria-label={t("strategyCollection.list")}>
      <p className="strategy-switcher-heading">{t("strategyCollection.list")}</p>
      {items.map((item) => <button key={item.id} type="button" role="menuitemradio" aria-checked={item.id === activeId}
        onClick={() => choose(() => onSelect(item.id))}>
        <i className="strategy-status-dot" data-running={item.running === true} aria-hidden="true" />
        <span><strong>{item.name}</strong>{item.meta && <small>{item.meta}</small>}</span>
        {item.id === activeId && <Icon name="check" size={13} />}
      </button>)}
      {actions.length > 0 && <hr />}
      {actions.map((action) => <button key={action.id} type="button" role="menuitem" disabled={action.disabled} title={action.title}
        onClick={() => choose(action.onSelect)}>
        <span>{action.label}</span>
      </button>)}
    </div>}
  </div>;
}
