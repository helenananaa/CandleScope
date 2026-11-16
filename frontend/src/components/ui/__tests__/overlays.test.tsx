import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { DialogSurface } from "../Overlays.js";
import { createOverlayStack, type OverlayEntry } from "../overlay/overlayStack.js";
import { placePopover } from "../overlay/position.js";
import { trappedFocusTarget } from "../overlay/overlayRuntime.js";
import { MAX_TOASTS, createToastStore } from "../overlay/toastStore.js";

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
