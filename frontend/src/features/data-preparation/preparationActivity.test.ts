import assert from "node:assert/strict";
import test from "node:test";
import type { PreparationJob } from "./api.js";
import { replayPreparationActivity, replayPreparationCompleted } from "./preparationActivity.js";

function job(id: string, state: PreparationJob["state"], consumer = "REPLAY"): PreparationJob {
  return { id, state, stage: "", completed: 0, total: 1, revision: 1, cancel_requested: false,
    request: { consumer, requirements: [{ symbol: "BTCUSDT" }], intent: {} }, result: null, error: null };
}

test("hundreds of completed tasks and strategy jobs do not crowd the replay home", () => {
  const history = Array.from({ length: 500 }, (_, i) => job(String(i), i % 2 ? "READY" : "CANCELLED"));
  const active = job("active", "RUNNING");
  const failed = job("failed", "FAILED");
  const blocked = job("blocked", "BLOCKED_STORAGE");
  const activity = replayPreparationActivity([...history, job("strategy", "FAILED", "STRATEGY"), job("prefetch", "RUNNING", "PREFETCH"), active, failed, blocked]);
  assert.deepEqual(activity.pending, [active, failed, blocked]);
  assert.equal(activity.failed, 2);
  assert.deepEqual(replayPreparationActivity(history), { pending: [], failed: 0 });
});

test("refresh training archives once when preparation completes, not on every poll", () => {
  const ready = job("a", "READY");
  assert.equal(replayPreparationCompleted([job("a", "RUNNING")], [ready]), true);
  assert.equal(replayPreparationCompleted([ready], [ready]), false);
  assert.equal(replayPreparationCompleted([], [ready]), false);
  assert.equal(replayPreparationCompleted([job("a", "RUNNING", "STRATEGY")], [job("a", "READY", "STRATEGY")]), false);
});
