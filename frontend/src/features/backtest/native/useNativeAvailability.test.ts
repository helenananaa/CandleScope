import assert from "node:assert/strict";
import test from "node:test";
import { nativeAvailability, resolveAvailableStrategyMode } from "./useNativeAvailability.js";

test("default mode follows actual engine capability, including Pyne-only installations", () => {
  assert.equal(nativeAvailability({ engines: [] }), "unavailable");
  assert.equal(nativeAvailability({ engines: [{ language: "pine", available: false, external_available: true }] }), "unavailable");
  const supported = nativeAvailability({ engines: [{ language: "pine", available: false }, { language: "pyne", available: true }] });
  assert.equal(resolveAvailableStrategyMode("NATIVE", supported), "NATIVE");
  for (const state of ["loading", "error", "unavailable"] as const) {
    assert.equal(resolveAvailableStrategyMode("NATIVE", state), "CANDLESCOPE");
    assert.equal(resolveAvailableStrategyMode("NATIVE", state, true), "NATIVE");
  }
  assert.equal(resolveAvailableStrategyMode("CANDLESCOPE", "available"), "CANDLESCOPE");
});
