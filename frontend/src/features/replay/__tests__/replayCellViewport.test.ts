import assert from "node:assert/strict";
import test from "node:test";
import { createReplayCellViewportRestore } from "../useReplayCellViewport.js";

test("reopened chart restores when ready, then history updates cannot overwrite user pan", () => {
  const saved = { from: 100, to: 200 };
  let ready = false;
  let visible = { from: 300, to: 400 };
  let attempts = 0;
  const restore = createReplayCellViewportRestore(saved, range => {
    attempts++;
    if (!ready) return false;
    visible = { ...range };
    return true;
  });
  assert.equal(restore(), false);
  assert.equal(restore(), false);
  ready = true;
  assert.equal(restore(), true);
  assert.deepEqual(visible, saved);
  visible = { from: 120, to: 220 }; // User pan after restoration.
  assert.equal(restore(), true); // History prepend readiness.
  assert.equal(restore(), true); // Indicator readiness / clock update.
  assert.deepEqual(visible, { from: 120, to: 220 });
  assert.equal(attempts, 3);
  assert.equal(createReplayCellViewportRestore(undefined, () => assert.fail("no saved range"))(), true);
});
