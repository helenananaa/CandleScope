import assert from "node:assert/strict";
import test from "node:test";
import { resolveStrategyTesterMode } from "../chartStrategyMode.js";

test("explicit native choice survives an existing teaching attachment", () => {
  assert.equal(resolveStrategyTesterMode("NATIVE", true), "NATIVE");
  assert.equal(resolveStrategyTesterMode("CANDLESCOPE", false), "CANDLESCOPE");
});

test("legacy and invalid modes retain the attachment-based default", () => {
  for (const value of [undefined, null, "broken"]) {
    assert.equal(resolveStrategyTesterMode(value, true), "CANDLESCOPE");
    assert.equal(resolveStrategyTesterMode(value, false), "NATIVE");
  }
});
