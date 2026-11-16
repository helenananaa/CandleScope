import {
  cloneElement, isValidElement, useCallback, useEffect, useId, useLayoutEffect, useRef, useState,
  type FocusEvent, type KeyboardEvent, type PointerEvent, type ReactElement, type ReactNode, type RefObject,
} from "react";
import { createPortal } from "react-dom";
import { t } from "../../i18n/index.js";
import { IconButton } from "./Button.js";
import { choiceKeyTarget } from "./helpers.js";
import { overlayHost, useOverlayLayer } from "./overlay/overlayRuntime.js";
import { placePopover, type Placement } from "./overlay/position.js";
import type { DrawerSide, OverlayKind } from "./overlay/overlayStack.js";

function CloseGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
      <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

export interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  /** Actions, primary last. */
  footer?: ReactNode;
  size?: "sm" | "md" | "lg";
  /** Escape, the close button and a backdrop click close it. False while work is running. */
  dismissible?: boolean;
  role?: "dialog" | "alertdialog";
  initialFocusRef?: RefObject<HTMLElement | null>;
  className?: string;
}

/** Modal dialog: above drawers, traps focus, returns focus on close, makes the page inert. */
export function Dialog(props: DialogProps) {
  if (!props.open || typeof document === "undefined") return null;
  return createPortal(<DialogLayer {...props} />, overlayHost());
}

function DialogLayer({ open, onClose, title, description, children, footer, size = "md", dismissible = true, role = "dialog", initialFocusRef, className }: DialogProps) {
  const layerRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const zIndex = useOverlayLayer({ open, kind: "modal", onClose, closeOnEscape: dismissible, layerRef, trapRef: panelRef, ...(initialFocusRef ? { initialFocusRef } : {}) });
  return (
    <div ref={layerRef} className="ui-dialog-layer" style={{ zIndex }}>
      <div className="ui-dialog-backdrop" aria-hidden="true" onMouseDown={dismissible ? onClose : undefined} />
      <DialogSurface ref={panelRef} role={role} titleId={titleId} descriptionId={description ? descriptionId : undefined}
        title={title} description={description} footer={footer} size={size} className={className}
        {...(dismissible ? { onClose } : {})}>
        {children}
      </DialogSurface>
    </div>
  );
}

export interface DialogSurfaceProps {
  ref?: RefObject<HTMLElement | null>;
  role: "dialog" | "alertdialog";
  titleId: string;
  descriptionId: string | undefined;
  title: ReactNode;
  description?: ReactNode;
  footer?: ReactNode;
  size: "sm" | "md" | "lg";
  className: string | undefined;
  onClose?: () => void;
  children?: ReactNode;
}

/** The dialog box itself (rendered by Dialog; exported for tests and static previews). */
export function DialogSurface({ ref, role, titleId, descriptionId, title, description, footer, size, className, onClose, children }: DialogSurfaceProps) {
  return (
    <section ref={ref} role={role} aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId} tabIndex={-1}
      className={["ui-dialog", `ui-dialog-${size}`, className].filter(Boolean).join(" ")}>
      <header className="ui-dialog-head">
        <div className="ui-dialog-heading">
          <h2 id={titleId} className="ui-dialog-title">{title}</h2>
          {description ? <p id={descriptionId} className="ui-dialog-description">{description}</p> : null}
        </div>
        {onClose ? <IconButton size="sm" label={t("common.close")} icon={<CloseGlyph />} onClick={onClose} data-overlay-close="" /> : null}
      </header>
      {children != null ? <div className="ui-dialog-body">{children}</div> : null}
      {footer ? <footer className="ui-dialog-foot">{footer}</footer> : null}
    </section>
  );
}

export interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  side?: DrawerSide;
  children?: ReactNode;
  footer?: ReactNode;
  /** Header actions next to the close button. */
  actions?: ReactNode;
  className?: string;
}

/** Side panel next to the page. One per side: opening another replaces it. Not modal. */
export function Drawer(props: DrawerProps) {
  if (!props.open || typeof document === "undefined") return null;
  return createPortal(<DrawerLayer {...props} />, overlayHost());
}

function DrawerLayer({ open, onClose, title, side = "right", children, footer, actions, className }: DrawerProps) {
  const layerRef = useRef<HTMLElement>(null);
  const titleId = useId();
  const zIndex = useOverlayLayer({ open, kind: "drawer", side, onClose, layerRef });
  return (
    <aside ref={layerRef} role="dialog" aria-labelledby={titleId} tabIndex={-1} data-side={side} style={{ zIndex }}
      className={["ui-drawer", className].filter(Boolean).join(" ")}>
      <header className="ui-drawer-head">
        <h2 id={titleId} className="ui-drawer-title">{title}</h2>
        <div className="ui-drawer-actions">
          {actions}
          <IconButton size="sm" label={t("common.close")} icon={<CloseGlyph />} onClick={onClose} data-overlay-close="" />
        </div>
      </header>
      <div className="ui-drawer-body">{children}</div>
      {footer ? <footer className="ui-drawer-foot">{footer}</footer> : null}
    </aside>
  );
}

export interface OverlayLayerProps {
  kind: OverlayKind;
  /** Drawers only. */
  side?: DrawerSide;
  onClose: () => void;
  /** False while work runs that Escape must not interrupt. */
  closeOnEscape?: boolean;
  /** Focused on open; defaults to the first control that is not a close button or resize handle. */
  initialFocusRef?: RefObject<HTMLElement | null>;
  /** Focused on close; defaults to whatever had focus on open. */
  returnFocusRef?: RefObject<HTMLElement | null>;
  children: ReactNode;
}

/**
 * Puts an existing overlay on the stack without restyling it. Its markup moves into the
 * overlay host inside a full-screen layer that takes the stack's z-index band, so its own
 * z-index values only order its parts. The layer joins the Escape order, returns focus to
 * the opener and, for modals, makes the page inert and keeps Tab inside.
 * New surfaces use Dialog, Drawer or Popover instead.
 */
export function OverlayLayer(props: OverlayLayerProps) {
  // Without a DOM (static rendering) the markup renders in place, unmanaged.
  if (typeof document === "undefined") return <>{props.children}</>;
  return createPortal(<ManagedLayer {...props} />, overlayHost());
}

function ManagedLayer({ kind, side, onClose, closeOnEscape = true, initialFocusRef, returnFocusRef, children }: OverlayLayerProps) {
  const layerRef = useRef<HTMLDivElement>(null);
  const zIndex = useOverlayLayer({
    open: true, kind, onClose, closeOnEscape, layerRef,
    ...(side ? { side } : {}),
    ...(kind === "modal" ? { trapRef: layerRef } : {}),
    ...(initialFocusRef ? { initialFocusRef } : {}),
    ...(returnFocusRef ? { returnFocusRef } : {}),
  });
  return <div ref={layerRef} className="ui-layer" data-overlay-kind={kind} style={{ zIndex }}>{children}</div>;
}

export interface PopoverProps {
  open: boolean;
  onClose: () => void;
  /** The control that opened it; focus returns there and the popover sits next to it. */
  anchorRef: RefObject<HTMLElement | null>;
  placement?: Placement;
  /** Accessible name. */
  label?: string;
  role?: "dialog" | "menu" | "listbox";
  children: ReactNode;
  className?: string;
  initialFocusRef?: RefObject<HTMLElement | null>;
}

/** Floating panel anchored to a control. Escape or a click outside closes it. */
export function Popover(props: PopoverProps) {
  if (!props.open || typeof document === "undefined") return null;
  return createPortal(<PopoverLayer {...props} />, overlayHost());
}

function PopoverLayer({ open, onClose, anchorRef, placement = "bottom-start", label, role = "dialog", children, className, initialFocusRef }: PopoverProps) {
  const layerRef = useRef<HTMLDivElement>(null);
  const zIndex = useOverlayLayer({ open, kind: "popover", onClose, layerRef, returnFocusRef: anchorRef, ...(initialFocusRef ? { initialFocusRef } : {}) });
  const [position, setPosition] = useState<{ top: number; left: number; maxHeight: number; placement: Placement } | null>(null);

  const place = useCallback(() => {
    const anchor = anchorRef.current, element = layerRef.current;
    if (!anchor || !element) return;
    const rect = anchor.getBoundingClientRect();
    const size = { width: element.offsetWidth, height: element.scrollHeight };
    setPosition(placePopover(rect, size, { width: window.innerWidth, height: window.innerHeight }, placement));
  }, [anchorRef, placement]);

  useLayoutEffect(() => {
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [place]);

  useEffect(() => {
    const onPointerDown = (event: globalThis.PointerEvent) => {
      const target = event.target as Node | null;
      if (!target || layerRef.current?.contains(target) || anchorRef.current?.contains(target)) return;
      onClose();
    };
    document.addEventListener("pointerdown", onPointerDown, true);
    return () => document.removeEventListener("pointerdown", onPointerDown, true);
  }, [anchorRef, onClose]);

  return (
    <div ref={layerRef} role={role} aria-label={label} tabIndex={-1} data-placement={position?.placement ?? placement}
      className={["ui-popover", className].filter(Boolean).join(" ")}
      style={{ zIndex, top: position?.top ?? -9999, left: position?.left ?? -9999, maxHeight: position?.maxHeight }}>
      {children}
    </div>
  );
}

export interface MenuItem {
  id: string;
  label: ReactNode;
  icon?: ReactNode;
  /** Keyboard shortcut shown at the end of the row. */
  hint?: ReactNode;
  tone?: "danger";
  disabled?: boolean;
  onSelect: () => void;
}

export interface MenuProps {
  open: boolean;
  onClose: () => void;
  anchorRef: RefObject<HTMLElement | null>;
  label: string;
  items: readonly MenuItem[];
  placement?: Placement;
}

/** Action menu: arrow keys move, Enter chooses, Escape closes and returns focus to the trigger. */
export function Menu({ open, onClose, anchorRef, label, items, placement = "bottom-start" }: MenuProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const firstRef = useRef<HTMLButtonElement>(null);
  const firstEnabled = items.findIndex((item) => !item.disabled);
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const buttons = [...(listRef.current?.querySelectorAll<HTMLButtonElement>("[role='menuitem']") ?? [])];
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const target = choiceKeyTarget(event.key, index < 0 ? -1 : index, buttons.map((b) => b.disabled));
    if (target == null) return;
    event.preventDefault();
    buttons[target]?.focus();
  };
  return (
    <Popover open={open} onClose={onClose} anchorRef={anchorRef} label={label} role="menu" placement={placement} initialFocusRef={firstRef} className="ui-menu">
      <div ref={listRef} className="ui-menu-list" onKeyDown={onKeyDown}>
        {items.map((item, index) => (
          <button key={item.id} ref={index === firstEnabled ? firstRef : undefined} type="button" role="menuitem" disabled={item.disabled}
            className="ui-menu-item" data-tone={item.tone} tabIndex={-1}
            onClick={() => { onClose(); item.onSelect(); }}>
            {item.icon ? <span className="ui-menu-icon" aria-hidden="true">{item.icon}</span> : null}
            <span className="ui-menu-label">{item.label}</span>
            {item.hint ? <span className="ui-menu-hint">{item.hint}</span> : null}
          </button>
        ))}
      </div>
    </Popover>
  );
}

export interface TooltipProps {
  content: ReactNode;
  /** One element that can take focus (a button or link). */
  children: ReactElement<{
    "aria-describedby"?: string | undefined;
    onPointerEnter?: (event: PointerEvent<HTMLElement>) => void;
    onPointerLeave?: (event: PointerEvent<HTMLElement>) => void;
    onFocus?: (event: FocusEvent<HTMLElement>) => void;
    onBlur?: (event: FocusEvent<HTMLElement>) => void;
  }>;
  placement?: Placement;
  delayMs?: number;
}

/** Short description shown on hover and keyboard focus; Escape hides it. */
export function Tooltip({ content, children, placement = "top", delayMs = 400 }: TooltipProps) {
  const id = useId();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const show = (element: HTMLElement, delay: number) => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setAnchor(element), delay);
  };
  const hide = () => {
    if (timer.current) clearTimeout(timer.current);
    setAnchor(null);
  };
  useEffect(() => {
    if (!anchor) return undefined;
    const onKeyDown = (event: globalThis.KeyboardEvent) => { if (event.key === "Escape") setAnchor(null); };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [anchor]);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  if (!isValidElement(children)) return children;
  const props = children.props;
  const trigger = cloneElement(children, {
    "aria-describedby": [props["aria-describedby"], anchor ? id : null].filter(Boolean).join(" ") || undefined,
    onPointerEnter: (event: PointerEvent<HTMLElement>) => { props.onPointerEnter?.(event); show(event.currentTarget, delayMs); },
    onPointerLeave: (event: PointerEvent<HTMLElement>) => { props.onPointerLeave?.(event); hide(); },
    onFocus: (event: FocusEvent<HTMLElement>) => { props.onFocus?.(event); if (event.currentTarget.matches(":focus-visible")) show(event.currentTarget, 0); },
    onBlur: (event: FocusEvent<HTMLElement>) => { props.onBlur?.(event); hide(); },
  });
  return (
    <>
      {trigger}
      {anchor && typeof document !== "undefined" ? createPortal(<TooltipBubble id={id} anchor={anchor} placement={placement}>{content}</TooltipBubble>, overlayHost()) : null}
    </>
  );
}

function TooltipBubble({ id, anchor, placement, children }: { id: string; anchor: HTMLElement; placement: Placement; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const placed = placePopover(anchor.getBoundingClientRect(), { width: element.offsetWidth, height: element.offsetHeight }, { width: window.innerWidth, height: window.innerHeight }, placement, 6);
    setPosition({ top: placed.top, left: placed.left });
  }, [anchor, placement]);
  return <div ref={ref} id={id} role="tooltip" className="ui-tooltip" style={{ top: position?.top ?? -9999, left: position?.left ?? -9999 }}>{children}</div>;
}
