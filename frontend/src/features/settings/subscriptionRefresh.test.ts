import assert from "node:assert/strict";
import test from "node:test";
import { refreshLines } from "./subscriptionRefresh.js";

const date = (ms: number) => `t${ms}`;

test("a subscription not checked yet says so", () => {
  assert.deepEqual(refreshLines(undefined, date), [{ key: "settings.proxy.refreshPending", values: {} }]);
  assert.deepEqual(refreshLines({ last_attempt_ms: 0 }, date), [{ key: "settings.proxy.refreshPending", values: {} }]);
});

test("a check lists when it ran, what it updated and what the provider dropped", () => {
  assert.deepEqual(refreshLines({ last_attempt_ms: 9, last_success_ms: 9, last_change_ms: 5, updated: 2, missing: 1, error: null }, date), [
    { key: "settings.proxy.refreshChecked", values: { time: "t9" } },
    { key: "settings.proxy.refreshUpdated", values: { count: 2, time: "t5" } },
    { key: "settings.proxy.refreshMissing", values: { count: 1 } },
  ]);
  assert.deepEqual(refreshLines({ last_attempt_ms: 9, last_success_ms: 9, missing: 0, error: null }, date), [
    { key: "settings.proxy.refreshChecked", values: { time: "t9" } },
  ]);
});

test("a failed check says when it failed and keeps the last update", () => {
  assert.deepEqual(refreshLines({ last_attempt_ms: 12, last_success_ms: 9, last_change_ms: 5, updated: 1, missing: 3, error: "Subscription returned HTTP 503" }, date), [
    { key: "settings.proxy.refreshFailed", values: { time: "t12" } },
    { key: "settings.proxy.refreshUpdated", values: { count: 1, time: "t5" } },
  ]);
});
