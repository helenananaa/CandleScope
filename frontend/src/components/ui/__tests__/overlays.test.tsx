import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { DialogSurface } from "../Overlays.js";
import { createOverlayStack, type OverlayEntry } from "../overlay/overlayStack.js";
import { placePopover } from "../overlay/position.js";
import { escapeClosesTopLayer, focusLeavesPopup, trappedFocusTarget } from "../overlay/overlayRuntime.js";
import { isContextMenuKey, menuItemRole, moveMenuFocus } from "../helpers.js";
import { MAX_TOASTS, createToastStore, toastStore } from "../overlay/toastStore.js";
import { ToastRegion } from "../Feedback.js";

function entry(id: string, kind: OverlayEntry["kind"], extra: Partial<OverlayEntry> = {}, closed: string[] = []): OverlayEntry {
  return { id, kind, requestClose: () => { closed.push(id); }, ...extra };
}

test("opening a drawer replaces the drawer on the same side only", () => {
  const stack = createOverlayStack();
  assert.deepEqual(stack.open(entry("alerts", "drawer", { side: "right" })), []);
  assert.deepEqual(stack.open(entry("layers", "drawer", { side: "left" })), []);
  const replaced = stack.open(entry("indicators", "drawer", { side: "right" }));
  assert.deepEqual(replaced.map((e) => e.id), ["alerts"]);
  assert.deepEqual(stack.layers().map((e) => e.id), ["layers", "indicators"]);
});

test("modals sit above drawers and popovers above both, whatever the open order", () => {
  const stack = createOverlayStack();
  stack.open(entry("search", "modal"));
  stack.open(entry("alerts", "drawer"));
  stack.open(entry("menu", "popover"));
  assert.deepEqual(stack.layers().map((e) => e.id), ["alerts", "search", "menu"]);
  const z = (id: string) => stack.zIndex(id) ?? 0;
  assert.ok(z("alerts") < z("search") && z("search") < z("menu"));
  assert.equal(stack.top()?.id, "menu");
});

test("a later modal stacks above an earlier one", () => {
  const stack = createOverlayStack();
  stack.open(entry("settings", "modal"));
  stack.open(entry("confirm", "modal"));
  assert.ok((stack.zIndex("confirm") ?? 0) > (stack.zIndex("settings") ?? 0));
  assert.equal(stack.inert("settings"), true);
  assert.equal(stack.inert("confirm"), false);
  assert.equal(stack.hasModal(), true);
});

test("Escape closes the topmost layer, one at a time", () => {
  const closed: string[] = [];
  const stack = createOverlayStack();
  stack.open(entry("alerts", "drawer", {}, closed));
  stack.open(entry("search", "modal", {}, closed));
  stack.open(entry("menu", "popover", {}, closed));
  assert.equal(stack.escape(), true);
  assert.deepEqual(closed, ["menu"]);
  stack.close("menu");
  stack.escape();
  assert.deepEqual(closed, ["menu", "search"]);
});

test("a layer that refuses Escape keeps it from closing anything below", () => {
  const closed: string[] = [];
  const stack = createOverlayStack();
  stack.open(entry("alerts", "drawer", {}, closed));
  stack.open(entry("running", "modal", { closeOnEscape: false }, closed));
  assert.equal(stack.escape(), false);
  assert.deepEqual(closed, []);
  assert.equal(createOverlayStack().escape(), false);
});

test("whether a layer refuses Escape is read when Escape is pressed", () => {
  const closed: string[] = [];
  const stack = createOverlayStack();
  let editing = true;
  stack.open(entry("indicators", "drawer", { closeOnEscape: () => !editing }, closed));
  assert.equal(stack.escape(), false);
  editing = false;
  assert.equal(stack.escape(), true);
  assert.deepEqual(closed, ["indicators"]);
});

test("Escape closes the top layer only after every other handler declined it", () => {
  const key = (extra: Partial<Parameters<typeof escapeClosesTopLayer>[0]> = {}) => ({
    key: "Escape", isComposing: false, keyCode: 27, defaultPrevented: false, cancelBubble: false, ...extra,
  });
  const open = { layersOpen: true, nativeModalOpen: false };
  assert.equal(escapeClosesTopLayer(key(), open), true);
  // A widget in the layer (an editor, a nested picker, a rename field) used it.
  assert.equal(escapeClosesTopLayer(key({ defaultPrevented: true }), open), false);
  assert.equal(escapeClosesTopLayer(key({ cancelBubble: true }), open), false);
  // Input methods use Escape to cancel composition.
  assert.equal(escapeClosesTopLayer(key({ isComposing: true }), open), false);
  assert.equal(escapeClosesTopLayer(key({ keyCode: 229 }), open), false);
  // A native modal <dialog> handles its own Escape; nothing to close without layers.
  assert.equal(escapeClosesTopLayer(key(), { layersOpen: true, nativeModalOpen: true }), false);
  assert.equal(escapeClosesTopLayer(key(), { layersOpen: false, nativeModalOpen: false }), false);
  assert.equal(escapeClosesTopLayer(key({ key: "Enter" }), open), false);
});

test("subscribers hear opens and closes", () => {
  const stack = createOverlayStack();
  let calls = 0;
  const unsubscribe = stack.subscribe(() => { calls++; });
  stack.open(entry("a", "modal"));
  stack.close("a");
  stack.close("missing");
  unsubscribe();
  stack.open(entry("b", "modal"));
  assert.equal(calls, 2);
});

test("popovers open below, flip above when short of room, and stay inside the viewport", () => {
  const viewport = { width: 1000, height: 800 };
  const below = placePopover({ top: 100, left: 50, width: 80, height: 30 }, { width: 200, height: 150 }, viewport);
  assert.deepEqual(below, { top: 136, left: 50, placement: "bottom-start", maxHeight: 656 });
  const flipped = placePopover({ top: 700, left: 50, width: 80, height: 30 }, { width: 200, height: 150 }, viewport);
  assert.equal(flipped.placement, "top-start");
  assert.equal(flipped.top, 700 - 6 - 150);
  const clamped = placePopover({ top: 100, left: 950, width: 40, height: 30 }, { width: 200, height: 100 }, viewport);
  assert.equal(clamped.left, 1000 - 200 - 8);
  const end = placePopover({ top: 100, left: 600, width: 100, height: 30 }, { width: 200, height: 100 }, viewport, "bottom-end");
  assert.equal(end.left, 500);
});

test("Tab wraps inside a focus trap", () => {
  const items = ["a", "b", "c"].map((id) => ({ id }) as unknown as HTMLElement);
  const [a, b, c] = items;
  assert.equal(trappedFocusTarget(items, c ?? null, false), a);
  assert.equal(trappedFocusTarget(items, a ?? null, true), c);
  assert.equal(trappedFocusTarget(items, b ?? null, false), null, "native Tab moves within the trap");
  assert.equal(trappedFocusTarget(items, null, false), a, "focus outside the trap comes back in");
  assert.equal(trappedFocusTarget([], null, false), null);
});

test("a page popup closes when focus moves on to the page, not into a layer it opened", () => {
  const node = (inside: Element[] = [], overlay = false): Element => {
    const self = {
      contains: (other: unknown) => other === self || inside.includes(other as Element),
      closest: (selector: string) => (overlay && selector.includes("data-overlay-root") ? {} : null),
    };
    return self as unknown as Element;
  };
  const item = node();
  const popup = node([item]);
  const trigger = node();
  const page = node();
  const confirmation = node([], true);
  assert.equal(focusLeavesPopup(item, popup, trigger), false, "within the popup");
  assert.equal(focusLeavesPopup(trigger, popup, trigger), false, "back to its trigger");
  assert.equal(focusLeavesPopup(confirmation, popup, trigger), false, "into a confirmation it opened");
  assert.equal(focusLeavesPopup(null, popup, trigger), false, "focus left the window");
  assert.equal(focusLeavesPopup(page, popup, trigger), true, "Tab past the last control");
});

test("menus move with the arrow keys, Home and End, skipping what cannot be chosen", () => {
  let active: unknown = null;
  const items = ["copy", "move", "remove"].map((id) => {
    const item = { id, focus: () => { active = item; }, getClientRects: () => [1], matches: () => id === "move" };
    return item;
  });
  active = items[0];
  const globals = globalThis as unknown as { document?: unknown };
  const previous = globals.document;
  globals.document = { get activeElement() { return active; } };
  try {
    const container = { querySelectorAll: () => items } as unknown as HTMLElement;
    let prevented = 0;
    const press = (key: string) => moveMenuFocus({ key, preventDefault: () => { prevented += 1; } }, container);
    assert.equal(press("ArrowDown"), true);
    assert.equal(active, items[2], "the disabled item is skipped");
    press("ArrowDown");
    assert.equal(active, items[0], "wraps around");
    press("End");
    assert.equal(active, items[2]);
    assert.equal(press("a"), false, "other keys are left alone");
    assert.equal(prevented, 3);
  } finally {
    globals.document = previous;
  }
  assert.equal(isContextMenuKey({ key: "F10", shiftKey: true }), true);
  assert.equal(isContextMenuKey({ key: "ContextMenu", shiftKey: false }), true);
  assert.equal(isContextMenuKey({ key: "F10", shiftKey: false }), false);
});

test("toasts keep the newest few and dismiss by id", () => {
  const store = createToastStore();
  const ids = Array.from({ length: MAX_TOASTS + 2 }, (_, i) => store.add({ title: `t${i}` }));
  assert.equal(store.list().length, MAX_TOASTS);
  assert.equal(store.list()[0]?.title, "t2");
  store.dismiss(ids[ids.length - 1] ?? -1);
  assert.equal(store.list().length, MAX_TOASTS - 1);
  assert.equal(store.add({ title: "x", tone: "danger" }) > 0, true);
  assert.equal(store.list().at(-1)?.durationMs, 8000);
  assert.equal(store.list().at(-2)?.durationMs, 5000);
});

test("a toast with a second action shows both under its message, the main one first", () => {
  const single = toastStore.add({ title: "One", action: { label: "Open", onClick: () => undefined } });
  const double = toastStore.add({ title: "Two", message: "Body", durationMs: 0,
    action: { label: "View release", onClick: () => undefined }, secondaryAction: { label: "Skip this version", onClick: () => undefined } });
  try {
    const html = renderToStaticMarkup(<ToastRegion />);
    const [first, second] = html.split('<div class="ui-toast"').slice(1);
    assert.doesNotMatch(first ?? "", /ui-toast-actions/, "one action stays beside the text");
    assert.match(first ?? "", /<\/div><button[^>]*>Open<\/button>/);
    assert.match(second ?? "", /<span class="ui-toast-message">Body<\/span><div class="ui-toast-actions"><button[^>]*class="ui-btn[^"]*"[^>]*>View release<\/button><button[^>]*ui-btn-ghost[^>]*>Skip this version<\/button><\/div><\/div>/);
    assert.equal(toastStore.list().at(-1)?.durationMs, 0);
  } finally {
    toastStore.dismiss(single);
    toastStore.dismiss(double);
  }
});

test("a dialog is labelled by its title and described by its description", () => {
  const html = renderToStaticMarkup(
    <DialogSurface role="alertdialog" titleId="t" descriptionId="d" title="Delete alert?" description="This cannot be undone." size="sm"
      className={undefined} onClose={() => undefined} footer={<button type="button">Delete</button>}>Body</DialogSurface>,
  );
  assert.match(html, /^<section role="alertdialog" aria-modal="true" aria-labelledby="t" aria-describedby="d" tabindex="-1" class="ui-dialog ui-dialog-sm">/);
  assert.match(html, /<h2 id="t" class="ui-dialog-title">Delete alert\?<\/h2>/);
  assert.match(html, /<p id="d" class="ui-dialog-description">This cannot be undone\.<\/p>/);
  assert.match(html, /aria-label="[^"]+"/, "the close button has a name");
  assert.match(html, /<footer class="ui-dialog-foot">/);
});

test("menu items are actions, toggles or one choice of a group", () => {
  assert.equal(menuItemRole({}), "menuitem");
  assert.equal(menuItemRole({ checked: false }), "menuitemcheckbox");
  assert.equal(menuItemRole({ checked: true, radio: true }), "menuitemradio");
});

test("a popover anchored to a point opens below it and stays inside the viewport", () => {
  const point = { top: 300, left: 1390, width: 0, height: 0 };
  const placed = placePopover(point, { width: 200, height: 160 }, { width: 1440, height: 900 });
  assert.equal(placed.top, 306);
  assert.equal(placed.left, 1232);
  assert.equal(placed.placement, "bottom-start");
});
