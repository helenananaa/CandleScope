/**
 * A long press on a touch screen opens the menus a right-click opens with a mouse, on one timer on
 * every device. Left to the browser, Android fires `contextmenu` after its own delay while the
 * finger is still down (in the chart, after the crosshair has already appeared) and may then
 * deliver the release as a click that closes what just opened; iOS Safari fires none at all.
 *
 * So the browser's own touch `contextmenu` is dropped. A primary touch held within LONG_PRESS_SLOP
 * of where it started for LONG_PRESS_MS dispatches a `contextmenu` PointerEvent (pointerType
 * "touch") at the finger, and the release that ends it makes no mouse events or click. A touch whose pointerdown
 * was already claimed (a drawing stroke prevents its default) is left alone.
 */
export const LONG_PRESS_MS = 500;
export const LONG_PRESS_SLOP = 10;
/** A click this soon after a long press ends is the release of that press. */
const RELEASE_CLICK_MS = 700;

const dispatched = new WeakSet<Event>();

/** Whether a context menu event came from a touch: a long press, or the browser's own. */
export function isTouchContextMenu(event: Event): boolean {
  return "pointerType" in event && (event as PointerEvent).pointerType === "touch";
}

interface Press {
  /** Read when the timer fires: handlers below the window see it after this listener. */
  readonly down: PointerEvent;
  readonly pointerId: number;
  readonly x: number;
  readonly y: number;
  readonly target: Element;
  readonly timer: ReturnType<typeof setTimeout>;
}

export function installTouchLongPress(view: Window = window): () => void {
  const doc = view.document;
  let press: Press | null = null;
  let touching = 0;
  let touchEndedAt = -Infinity;
  let fired = false;
  let releasingLongPress = false;
  let swallowClickUntil = -Infinity;
  const now = () => view.performance.now();

  const cancel = () => {
    if (press) clearTimeout(press.timer);
    press = null;
  };

  const fire = () => {
    const current = press;
    press = null;
    if (!current?.target.isConnected || current.down.defaultPrevented) return;
    fired = true;
    const event = new PointerEvent("contextmenu", {
      bubbles: true,
      cancelable: true,
      composed: true,
      clientX: current.x,
      clientY: current.y,
      button: 2,
      pointerId: current.pointerId,
      pointerType: "touch",
      isPrimary: true,
    });
    dispatched.add(event);
    current.target.dispatchEvent(event);
  };

  const onPointerDown = (event: PointerEvent) => {
    if (event.pointerType !== "touch") return;
    touching += 1;
    cancel();
    if (!event.isPrimary || !(event.target instanceof Element)) return;
    press = {
      down: event,
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      target: event.target,
      timer: setTimeout(fire, LONG_PRESS_MS),
    };
  };

  const onPointerMove = (event: PointerEvent) => {
    if (!press || event.pointerId !== press.pointerId) return;
    if (Math.hypot(event.clientX - press.x, event.clientY - press.y) > LONG_PRESS_SLOP) cancel();
  };

  const onPointerEnd = (event: PointerEvent) => {
    if (event.pointerType !== "touch") return;
    touching = Math.max(0, touching - 1);
    if (press?.pointerId === event.pointerId) cancel();
    if (touching > 0) return;
    touchEndedAt = now();
    if (fired) {
      releasingLongPress = true;
      swallowClickUntil = touchEndedAt + RELEASE_CLICK_MS;
    }
    fired = false;
  };

  // The release of a long press makes no mouse events: the mousedown a browser derives from it
  // would land outside the menu that just opened and close it.
  const onTouchEnd = (event: TouchEvent) => {
    if (!releasingLongPress || event.touches.length > 0) return;
    releasingLongPress = false;
    if (event.cancelable) event.preventDefault();
  };

  const onContextMenu = (event: Event) => {
    if (dispatched.has(event)) return;
    const fromTouch = isTouchContextMenu(event) || touching > 0 || now() - touchEndedAt < RELEASE_CLICK_MS;
    if (!fromTouch) return;
    event.preventDefault();
    event.stopImmediatePropagation();
  };

  const onClick = (event: MouseEvent) => {
    if (now() > swallowClickUntil) return;
    swallowClickUntil = -Infinity;
    event.preventDefault();
    event.stopImmediatePropagation();
  };

  const capture = { capture: true } as const;
  view.addEventListener("pointerdown", onPointerDown, capture);
  view.addEventListener("pointermove", onPointerMove, capture);
  view.addEventListener("pointerup", onPointerEnd, capture);
  view.addEventListener("pointercancel", onPointerEnd, capture);
  view.addEventListener("contextmenu", onContextMenu, capture);
  view.addEventListener("click", onClick, capture);
  view.addEventListener("touchend", onTouchEnd, { capture: true, passive: false });
  // iOS: no callout or loupe for the press itself.
  doc.documentElement.style.setProperty("-webkit-touch-callout", "none");
  return () => {
    cancel();
    view.removeEventListener("pointerdown", onPointerDown, capture);
    view.removeEventListener("pointermove", onPointerMove, capture);
    view.removeEventListener("pointerup", onPointerEnd, capture);
    view.removeEventListener("pointercancel", onPointerEnd, capture);
    view.removeEventListener("contextmenu", onContextMenu, capture);
    view.removeEventListener("click", onClick, capture);
    view.removeEventListener("touchend", onTouchEnd, { capture: true });
    doc.documentElement.style.removeProperty("-webkit-touch-callout");
  };
}
