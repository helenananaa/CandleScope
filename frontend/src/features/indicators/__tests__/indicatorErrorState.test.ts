import assert from "node:assert/strict";
import test from "node:test";
import { ChartWorkScheduler } from "../../market-data/chartWorkScheduler.js";
import { indicatorRangeFailureMessage, updateIndicatorErrorState } from "../indicatorErrorState.js";
import type { IndicatorDefinition } from "../indicatorTypes.js";

test("a minimized window's rejected range cannot feed an indicator state/retry loop", async () => {
  const scheduler = new ChartWorkScheduler();
  scheduler.registerCell("chart", "focused");
  scheduler.setWindowVisible(false);
  const original: IndicatorDefinition[] = [{ id: "rsi", name: "RSI", error: null }];
  let state = original;
  let attempts = 0;
  let requests = 0;
  // React reruns the range effect when its indicator-state dependency changes.
  // Bound the model so regression reports a failure instead of hanging tests.
  for (; attempts < 10; attempts += 1) {
    const before = state;
    try {
      await scheduler.run("chart", "indicator-range", () => { requests += 1; });
    } catch (error) {
      const message = indicatorRangeFailureMessage(error);
      if (message !== null) state = updateIndicatorErrorState(state, "rsi", message);
    }
    if (state === before) break;
  }
  assert.equal(attempts, 0);
  assert.equal(requests, 0);
  assert.equal(state, original);
  scheduler.setWindowVisible(true);
  await scheduler.run("chart", "indicator-range", () => { requests += 1; });
  assert.equal(requests, 1, "the retained range can run after restoring the window");
  scheduler.dispose();
});

test("real errors remain visible without changing state for the same repeated failure", () => {
  const original: IndicatorDefinition[] = [{ id: "rsi", name: "RSI" }, { id: "vol", name: "Volume" }];
  const message = indicatorRangeFailureMessage(new Error("HTTP 503"));
  assert.equal(message, "HTTP 503");
  const updated = updateIndicatorErrorState(original, "rsi", message!);
  assert.notEqual(updated, original);
  assert.equal(updated[0]?.error, "HTTP 503");
  assert.equal(updated[1], original[1]);
  assert.equal(updateIndicatorErrorState(updated, "rsi", message!), updated);
  assert.equal(updateIndicatorErrorState(updated, "removed", "error"), updated);
});
