import assert from "node:assert/strict";
import test from "node:test";
import { listenForSearchContextMenuDismiss } from "../searchContextMenuDismiss.js";

test("background market scrolling leaves the menu open, but search scrolling closes it", () => {
  const windowTarget = new EventTarget();
  const modalTarget = new EventTarget();
  let dismissals = 0;
  const remove = listenForSearchContextMenuDismiss(windowTarget, modalTarget, () => { dismissals += 1; });
  windowTarget.dispatchEvent(new Event("scroll"));
  assert.equal(dismissals, 0);
  modalTarget.dispatchEvent(new Event("scroll"));
  assert.equal(dismissals, 1);
  remove();
});

test("outside actions and resize dismiss the menu, and cleanup removes all listeners", () => {
  const windowTarget = new EventTarget();
  const modalTarget = new EventTarget();
  let dismissals = 0;
  const remove = listenForSearchContextMenuDismiss(windowTarget, modalTarget, () => { dismissals += 1; });
  for (const type of ["click", "contextmenu", "resize"]) windowTarget.dispatchEvent(new Event(type));
  assert.equal(dismissals, 3);
  remove();
  for (const type of ["click", "contextmenu", "resize"]) windowTarget.dispatchEvent(new Event(type));
  modalTarget.dispatchEvent(new Event("scroll"));
  assert.equal(dismissals, 3);
});
