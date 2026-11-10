import assert from "node:assert/strict";
import test from "node:test";
import { mergeRepair, repairProgress } from "./continuousRepairView.js";
import type { ContinuousRepair } from "./continuousTypes.js";

const repair: ContinuousRepair = {
  id: "repair-one", request_key: "repair/stable", run_id: "one", phase: "PREPARING", target_revision: 10,
  plan_id: "a".repeat(64), base_identity: { id: "one", generation: 1, revision: 2, checkpoint_revision: 2,
    sequence: 25, event_time_ms: 1499999, data_revision: "old-source" },
  resume_after: false, from_ms: 600000, through_ms: 1499999, original_from_ms: 0,
  anchor_sequence: 10, full_reinitialization: false, expanded_range_reason: null,
  progress: { state: "REPLAYING", sequence: 15, event_time_ms: 899999 }, error: null, updated_at_ms: 100,
};

test("repair progress counts recomputed suffix BARs and never a guessed financial balance", () => {
  assert.deepEqual(repairProgress(repair), { done: 5, total: 15 });
  assert.deepEqual(repairProgress({ ...repair, phase: "COMMITTED" }), { done: 15, total: 15 });
  assert.deepEqual(repairProgress({ ...repair, progress: null }), { done: 0, total: 15 });
});

test("late HTTP status cannot rewind socket progress, an adopted repair, or a later request", () => {
  const current = mergeRepair(null, repair, "one")!;
  assert.equal(Object.isFrozen(current), true); assert.equal(Object.isFrozen(current.progress), true);
  assert.equal(Object.isFrozen(repair), false);
  assert.equal(mergeRepair(current, { ...repair, progress: { sequence: 10 }, updated_at_ms: 101 }, "one"), current);
  const committed = mergeRepair(current, { ...repair, phase: "COMMITTED", updated_at_ms: 200 }, "one")!;
  assert.equal(mergeRepair(committed, repair, "one"), committed);
  const next = mergeRepair(committed, { ...repair, id: "later", target_revision: 11, phase: "REQUESTED", updated_at_ms: 201 }, "one")!;
  assert.equal(mergeRepair(next, committed, "one"), next);
  assert.equal(mergeRepair(next, null, "one"), next);
});

test("wrong account, invalid clock and ambiguous epoch fail before progress publication", () => {
  for (const value of [{ ...repair, run_id: "other" }, { ...repair, from_ms: 1 },
    { ...repair, through_ms: NaN }, { ...repair, progress: { sequence: -1 } }])
    assert.throws(() => mergeRepair(null, value, "one"), { code: "CONTINUOUS_VIEW_INVALID" });
  const current = mergeRepair(null, repair, "one")!;
  assert.throws(() => mergeRepair(current, { ...repair, id: "different" }, "one"), { code: "CONTINUOUS_VIEW_INVALID" });
});
