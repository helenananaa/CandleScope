import assert from "node:assert/strict";
import test from "node:test";

import { createReplayOrderAdvisoryScheduler } from "../replayOrderAdvisoryScheduler.js";
import { replayOrderIsolatedAllocation } from "../replayOrderSizing.js";

const context = {
  marginMode: "ISOLATED" as const,
  positionMode: "HEDGE" as const,
  trackId: "track-1",
  positionSide: "LONG" as const,
};

test("zero-cap advisory refreshes after the selected isolated leg is funded or released", () => {
  let pending: (() => void) | null = null;
  const scheduler = createReplayOrderAdvisoryScheduler({
    timers: {
      setTimeout(callback) { pending = callback; return 1; },
      clearTimeout() { pending = null; },
    },
  });
  const quotedAllocations: string[] = [];
  const quote = (allocations: Record<string, string>) => {
    const allocation = replayOrderIsolatedAllocation({ ...context, allocations });
    const scheduled = scheduler.schedule(JSON.stringify(["track-1", allocation, "BUY"]), () => {
      quotedAllocations.push(allocation!);
    });
    pending?.();
    pending = null;
    return scheduled;
  };

  assert.equal(quote({}), true); // The original authoritative capacity is zero.
  assert.equal(quote({ "track-1:LONG": "500" }), true);
  assert.equal(quote({ "track-1:LONG": "500", "track-1:SHORT": "500" }), false);
  assert.equal(quote({ "track-1:LONG": "100", "track-1:SHORT": "500" }), true);
  assert.equal(quote({ "track-1:SHORT": "500" }), true);
  assert.deepEqual(quotedAllocations, ["0", "500", "100", "0"]);
});

test("hedge legs and tracks have independent explicit funding contexts", () => {
  const allocations = { "track-1:LONG": "500", "track-1:SHORT": "100", "track-2:LONG": "25" };
  assert.equal(replayOrderIsolatedAllocation({ ...context, allocations }), "500");
  assert.equal(replayOrderIsolatedAllocation({ ...context, allocations, positionSide: "SHORT" }), "100");
  assert.equal(replayOrderIsolatedAllocation({ ...context, allocations, trackId: "track-2" }), "25");
});

test("one-way isolated allocation uses the track and cross margin ignores allocation records", () => {
  const allocations = { "track-1": "250", "track-1:LONG": "500" };
  assert.equal(replayOrderIsolatedAllocation({ ...context, allocations, positionMode: "ONE_WAY" }), "250");
  assert.equal(replayOrderIsolatedAllocation({ ...context, allocations, marginMode: "CROSS" }), null);
  assert.equal(replayOrderIsolatedAllocation({ ...context, allocations, marginMode: undefined }), null);
});

test("market cursor churn and unrelated equity changes do not change the funding context", () => {
  const before = { ...context, allocations: { "track-1:LONG": "500" }, revision: 1, equity: "10000" };
  const after = { ...before, revision: 1_000, equity: "9998" };
  assert.equal(replayOrderIsolatedAllocation(before), replayOrderIsolatedAllocation(after));
});
