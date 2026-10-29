import assert from "node:assert/strict";
import test from "node:test";
import type { DesktopWindowLifecycleEvent } from "../../../desktop/desktopWindowManager.js";
import { observeMarketWindowVisibility } from "../marketWindowVisibility.js";

test("native restore and document visibility share one transition with conjunctive state", () => {
  const document = Object.assign(new EventTarget(), { visibilityState: "visible" as DocumentVisibilityState });
  let native!: (event: DesktopWindowLifecycleEvent) => void;
  let released = 0;
  const observed: boolean[] = [];
  const stop = observeMarketWindowVisibility((visible) => observed.push(visible), {
    document,
    desktop: { windowId: "main", onLifecycle: (listener) => { native = listener; return () => { released++; }; } },
  });
  const event = (state: DesktopWindowLifecycleEvent["state"], windowId = "main") => native({
    windowId, state, focused: false, visible: true, minimized: state === "minimized",
    placement: { boundsDip: { x: 0, y: 0, width: 800, height: 600 }, monitorFingerprint: null, dpiScale: 1, windowState: "normal" },
  });
  event("minimized", "other");
  assert.deepEqual(observed, [true]);
  event("minimized"); // document remains visible: the macOS F1 condition.
  document.dispatchEvent(new Event("visibilitychange"));
  assert.deepEqual(observed, [true, false]);
  event("restored");
  event("focused");
  assert.deepEqual(observed, [true, false, true]);
  document.visibilityState = "hidden";
  document.dispatchEvent(new Event("visibilitychange"));
  event("shown"); // Native events cannot override a genuinely hidden document.
  assert.deepEqual(observed, [true, false, true, false]);
  document.visibilityState = "visible";
  document.dispatchEvent(new Event("visibilitychange"));
  stop(); stop();
  event("minimized");
  document.dispatchEvent(new Event("visibilitychange"));
  assert.deepEqual(observed, [true, false, true, false, true]);
  assert.equal(released, 1);
});

test("mounting into an already hidden document immediately reports suspension", () => {
  const document = Object.assign(new EventTarget(), { visibilityState: "hidden" as DocumentVisibilityState });
  const observed: boolean[] = [];
  const stop = observeMarketWindowVisibility((visible) => observed.push(visible), {
    document, desktop: { windowId: "main", onLifecycle: () => () => undefined },
  });
  assert.deepEqual(observed, [false]);
  stop();
});
