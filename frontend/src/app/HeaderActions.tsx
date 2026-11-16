import { useCallback, useLayoutEffect, useRef, useState, type MutableRefObject } from "react";
import { Menu } from "../components/ui/index.js";
import { Icon } from "../components/icons/Icon.js";
import { t } from "../i18n/index.js";
import { fitHeaderActions } from "./headerActionsModel.js";

/** A page action in the app header. Actions that do not fit move into the 更多 menu, in order. */
export interface HeaderAction {
  id: string;
  label: string;
  /** Not called for a link (href). */
  onSelect(): void;
  /** Open state of the panel or popover this action toggles. */
  expanded?: boolean;
  hasPopup?: "dialog" | "menu";
  disabled?: boolean;
  title?: string;
  /** Set to the element a popover should anchor to: the action's button, or the 更多 button while the action is in its menu. */
  anchorRef?: MutableRefObject<HTMLElement | null>;
  /** id of the panel this action opens (aria-controls). */
  controls?: string;
  /** Opens this address in a new window instead of calling onSelect. */
  href?: string;
  /** data-* attributes for tests and automation, without the "data-" prefix. */
  data?: Readonly<Record<string, string>>;
}

function openExternal(href: string): void {
  window.open(href, "_blank", "noopener,noreferrer");
}

export default function HeaderActions({ actions }: { actions: readonly HeaderAction[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const moreRef = useRef<HTMLButtonElement>(null);
  const buttons = useRef(new Map<string, HTMLElement>());
  const [visible, setVisible] = useState(actions.length);
  const [menuOpen, setMenuOpen] = useState(false);
  const layoutKey = actions.map((action) => `${action.id}\u0000${action.label}`).join("\u0001");
  const measure = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const ids = layoutKey ? layoutKey.split("\u0001").map((entry) => entry.split("\u0000")[0] ?? "") : [];
    const widths = ids.map((id) => buttons.current.get(id)?.offsetWidth ?? 0);
    const gap = Number.parseFloat(getComputedStyle(container).columnGap) || 0;
    setVisible(fitHeaderActions(widths, container.clientWidth, gap, moreRef.current?.offsetWidth ?? 0));
  }, [layoutKey]);
  useLayoutEffect(() => {
    measure();
    const container = containerRef.current;
    if (!container || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(() => measure());
    observer.observe(container);
    return () => observer.disconnect();
  }, [measure]);
  // Popovers anchor to whatever the user can see: the button, or 更多 while the action is in the menu.
  useLayoutEffect(() => {
    actions.forEach((action, index) => {
      if (action.anchorRef) action.anchorRef.current = index < visible ? buttons.current.get(action.id) ?? null : moreRef.current;
    });
  });
  if (!actions.length) return null;
  const overflow = actions.slice(visible);
  return (
    <div ref={containerRef} className="app-header-actions">
      {actions.map((action, index) => {
        const shared = {
          className: "ui-control",
          "data-header-action": action.id,
          "data-overflow": index >= visible ? "true" : undefined,
          title: action.title,
          ...Object.fromEntries(Object.entries(action.data ?? {}).map(([name, value]) => [`data-${name}`, value])),
        };
        const register = (element: HTMLElement | null) => { if (element) buttons.current.set(action.id, element); else buttons.current.delete(action.id); };
        return action.href
          ? <a key={action.id} ref={register} {...shared} href={action.href} target="_blank" rel="noopener noreferrer">{action.label}</a>
          : (
            <button
              key={action.id}
              ref={register}
              type="button"
              {...shared}
              aria-expanded={action.expanded}
              aria-haspopup={action.hasPopup}
              aria-controls={action.controls}
              disabled={action.disabled}
              onClick={action.onSelect}
            >
              {action.label}
            </button>
          );
      })}
      <button
        ref={moreRef}
        type="button"
        className="ui-control app-header-more"
        data-overflow={overflow.length ? undefined : "true"}
        aria-label={t("shell.moreActions")}
        title={t("shell.moreActions")}
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        onClick={() => setMenuOpen((open) => !open)}
      >
        <Icon name="more" size={16} />
      </button>
      <Menu
        open={menuOpen && overflow.length > 0}
        onClose={() => setMenuOpen(false)}
        anchorRef={moreRef}
        placement="bottom-end"
        label={t("shell.moreActions")}
        items={overflow.map((action) => ({
          id: action.id,
          label: action.label,
          ...(action.disabled ? { disabled: true } : {}),
          onSelect: action.href ? () => openExternal(action.href ?? "/") : action.onSelect,
        }))}
      />
    </div>
  );
}
