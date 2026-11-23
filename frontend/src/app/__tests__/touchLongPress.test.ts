import assert from "node:assert/strict";
import { mock, test } from "node:test";

import { LONG_PRESS_MS, LONG_PRESS_SLOP, installTouchLongPress, isTouchContextMenu } from "../touchLongPress.js";

type Listener = (event: FakeEvent) => void;

class FakeElement {
  isConnected = true;
  readonly received: FakeEvent[] = [];
  dispatchEvent(event: FakeEvent): boolean {
    this.received.push(event);
    return true;
  }
}

class FakeEvent {
  defaultPrevented = false;
  stopped = false;
  readonly cancelable = true;
  constructor(readonly type: string, init: Record<string, unknown> = {}) {
    Object.assign(this, init);
  }
  preventDefault(): void { this.defaultPrevented = true; }
  stopImmediatePropagation(): void { this.stopped = true; }
}

/** A window whose listeners run in registration order, as capture listeners on the window do. */
function fakeWindow() {
  const listeners = new Map<string, Listener[]>();
  let clock = 0;
  const style = new Map<string, string>();
  const view = {
    document: { documentElement: { style: { setProperty: (k: string, v: string) => style.set(k, v), removeProperty: (k: string) => style.delete(k) } } },
    performance: { now: () => clock },
    addEventListener: (type: string, listener: Listener) => listeners.set(type, [...(listeners.get(type) ?? []), listener]),
    removeEventListener: (type: string, listener: Listener) => listeners.set(type, (listeners.get(type) ?? []).filter((l) => l !== listener)),
  };
  const fire = (type: string, init: Record<string, unknown> = {}) => {
    const event = new FakeEvent(type, init);
    for (const listener of listeners.get(type) ?? []) {
      listener(event);
      if (event.stopped) break;
    }
    return event;
  };
  return { view, fire, style, advance: (ms: number) => { clock += ms; mock.timers.tick(ms); } };
}

function setup() {
  mock.timers.enable({ apis: ["setTimeout"] });
  const scope = globalThis as Record<string, unknown>;
  const saved = { Element: scope.Element, PointerEvent: scope.PointerEvent };
  scope.Element = FakeElement;
  scope.PointerEvent = FakeEvent;
  const win = fakeWindow();
  const uninstall = installTouchLongPress(win.view as unknown as Window);
  const target = new FakeElement();
  const touch = (type: string, x = 100, y = 200, extra: Record<string, unknown> = {}) =>
    win.fire(type, { pointerType: "touch", pointerId: 7, isPrimary: true, clientX: x, clientY: y, target, ...extra });
  return {
    ...win, target, touch,
    done() { uninstall(); mock.timers.reset(); Object.assign(scope, saved); },
  };
}

test("a touch held still opens the context menu at the finger, and its release is no click", () => {
  const t = setup();
  try {
    assert.equal(t.style.get("-webkit-touch-callout"), "none");
    t.touch("pointerdown");
    t.advance(LONG_PRESS_MS - 1);
    assert.equal(t.target.received.length, 0);
    t.advance(1);
    const [menu] = t.target.received;
    assert.equal(menu?.type, "contextmenu");
    assert.ok(menu && isTouchContextMenu(menu as unknown as Event));
    assert.deepEqual([(menu as unknown as PointerEvent).clientX, (menu as unknown as PointerEvent).clientY], [100, 200]);
    t.touch("pointerup");
    assert.equal(t.fire("touchend", { touches: [] }).defaultPrevented, true, "no mouse events from the release");
    const click = t.fire("click");
    assert.equal(click.defaultPrevented && click.stopped, true, "the release is not a click");
    t.advance(1000);
    assert.equal(t.fire("click").stopped, false, "later clicks pass");
  } finally {
    t.done();
  }
});

test("moving past the slop, lifting early or a claimed press opens nothing", () => {
  const t = setup();
  try {
    t.touch("pointerdown");
    t.touch("pointermove", 100 + LONG_PRESS_SLOP + 1, 200);
    t.advance(LONG_PRESS_MS);
    t.touch("pointerup");
    t.touch("pointerdown");
    t.advance(LONG_PRESS_MS - 100);
    t.touch("pointerup");
    t.advance(200);
    t.touch("pointerdown").preventDefault();
    t.advance(LONG_PRESS_MS);
    t.touch("pointerup");
    assert.equal(t.target.received.length, 0);
    assert.equal(t.fire("touchend", { touches: [] }).defaultPrevented, false);
    assert.equal(t.fire("click").stopped, false, "a short tap still clicks");
  } finally {
    t.done();
  }
});

test("the browser's own touch context menu is dropped and a mouse one passes", () => {
  const t = setup();
  try {
    const touchMenu = t.fire("contextmenu", { pointerType: "touch" });
    assert.equal(touchMenu.defaultPrevented && touchMenu.stopped, true);
    t.touch("pointerdown");
    const duringPress = t.fire("contextmenu", { pointerType: "mouse" });
    assert.equal(duringPress.stopped, true, "a menu event while a finger is down comes from that finger");
    t.touch("pointerup");
    t.advance(1000);
    const mouseMenu = t.fire("contextmenu", { pointerType: "mouse" });
    assert.equal(mouseMenu.defaultPrevented || mouseMenu.stopped, false);
  } finally {
    t.done();
  }
});
