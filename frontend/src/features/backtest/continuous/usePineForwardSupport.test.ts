import assert from "node:assert/strict";
import test from "node:test";
import { setLocale } from "../../../i18n/index.js";
import { pineForwardRefusal } from "./usePineForwardSupport.js";

test("the native list names why a Pine strategy cannot track forward, or offers it (B-333b)", () => {
  setLocale("en");
  assert.equal(pineForwardRefusal({ state: "ready", support: { supported: true, uses: [], reason: null } }), null);
  assert.equal(pineForwardRefusal({ state: "ready", support: { supported: false, uses: ["calc_on_every_tick", "request.* datasets"], reason: "x" } }),
    "Forward tracking places close-bar Pine orders; this script uses calc_on_every_tick, request.* datasets.");
  // Until the backend answers, the entry waits rather than offering a run it may refuse.
  assert.equal(pineForwardRefusal(null), "Checking whether this script can run forward…");
  assert.equal(pineForwardRefusal({ state: "checking" }), "Checking whether this script can run forward…");
  assert.equal(pineForwardRefusal({ state: "failed", message: "line 3: mismatched input" }),
    "The script must compile before it can be tracked forward. line 3: mismatched input");
});
