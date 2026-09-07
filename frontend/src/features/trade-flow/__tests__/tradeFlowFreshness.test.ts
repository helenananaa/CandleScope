import assert from "node:assert/strict";
import test from "node:test";
import { isTradeFlowQuiet, latestTradeTime } from "../tradeFlowFreshness.js";

test("old trade times stop implying fresh data, without overriding connection failures", () => {
  assert.equal(isTradeFlowQuiet("live", 100_000, 159_999), false);
  assert.equal(isTradeFlowQuiet("live", 100_000, 160_000), true);
  assert.equal(isTradeFlowQuiet("live", 100_000, 9_000_000), true);
  assert.equal(isTradeFlowQuiet("live", 9_000_000, 9_000_001), false);
  assert.equal(isTradeFlowQuiet("live", null, 9_000_000), false);
  assert.equal(isTradeFlowQuiet("live", 9_000_001, 9_000_000), false);
  for (const status of ["waiting", "connecting", "reconnecting", "error", "gap", "idle", "unsupported"] as const) {
    assert.equal(isTradeFlowQuiet(status, 100_000, 9_000_000), false);
  }
});

test("freshness uses newest time even when trade identifiers are not time ordered", () => {
  assert.equal(latestTradeTime([]), null);
  assert.equal(latestTradeTime([{ tradeTimeMs: 100 }, { tradeTimeMs: 300 }, { tradeTimeMs: 200 }]), 300);
});
