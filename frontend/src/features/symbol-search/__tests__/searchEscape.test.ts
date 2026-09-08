import assert from "node:assert/strict";
import test from "node:test";
import { listenForSearchEscape } from "../searchEscape.js";

function keyEvent(key: string) {
  return Object.assign(new Event("keydown", { cancelable: true, bubbles: true }), { key });
}

test("search consumes Escape regardless of focus and releases it on close", () => {
  const document = new EventTarget();
  let dismissals = 0;
  const cleanup = listenForSearchEscape(document, () => { dismissals += 1; });
  const escape = keyEvent("Escape");
  document.dispatchEvent(escape);
  assert.equal(dismissals, 1);
  assert.equal(escape.defaultPrevented, true);
  document.dispatchEvent(keyEvent("ArrowDown"));
  const handled = keyEvent("Escape");
  handled.preventDefault();
  document.dispatchEvent(handled);
  assert.equal(dismissals, 1);
  cleanup();
  const afterClose = keyEvent("Escape");
  document.dispatchEvent(afterClose);
  assert.equal(dismissals, 1);
  assert.equal(afterClose.defaultPrevented, false);
});
