import assert from "node:assert/strict";
import test from "node:test";
import { chartFollowStatus, chartFollowStatusLabel, chartFollowStatusTone } from "../chartStrategyFollowStatus.js";

const MINUTE = 60_000;
// A 1m bar opened 13:02 UTC closes one millisecond before 13:03.
const BAR = Date.UTC(2026, 10, 22, 13, 2);
const live = (sourceState: string, throughMs: number | null = BAR + MINUTE - 1) => ({ sourceState, throughMs });

test("a followed result says whether it is live, waiting, recalculating or stopped, with its newest bar", () => {
  const base = { following: true, refused: false, shown: true, intervalMs: MINUTE };
  assert.equal(chartFollowStatus({ ...base, following: false, live: live("LIVE") }), null, "nothing is said without a FOLLOW run");
  assert.deepEqual(chartFollowStatus({ ...base, live: live("LIVE") }), { state: "live", latestBarMs: BAR });
  assert.deepEqual(chartFollowStatus({ ...base, live: live("WAITING_DATA") }), { state: "waiting", latestBarMs: BAR });
  assert.deepEqual(chartFollowStatus({ ...base, live: live("CATCHING_UP") }), { state: "recalculating", latestBarMs: BAR },
    "after it was shown, catching up again means revised bars are being recomputed");
  for (const ended of ["FAILED", "STOPPED"]) {
    assert.deepEqual(chartFollowStatus({ ...base, live: live(ended) }), { state: "stopped", latestBarMs: BAR });
  }
});

test("until the live run has caught up the fixed result is shown and the cell is connecting; a refusal is said once", () => {
  const base = { following: true, refused: false, shown: false, intervalMs: MINUTE };
  assert.deepEqual(chartFollowStatus({ ...base, live: null }), { state: "connecting", latestBarMs: null });
  assert.deepEqual(chartFollowStatus({ ...base, shown: true, live: null }), { state: "connecting", latestBarMs: null });
  assert.deepEqual(chartFollowStatus({ ...base, shown: true, live: live("LIVE", null) }), { state: "connecting", latestBarMs: null },
    "a live run that applied no bar yet has no newest bar to name");
  assert.deepEqual(chartFollowStatus({ ...base, refused: true, live: null }), { state: "unavailable", latestBarMs: null });
});

test("labels name the newest bar by its open time in UTC; tones reuse the dock's status dots", () => {
  const label = chartFollowStatusLabel({ state: "live", latestBarMs: BAR });
  assert.match(label, /13:02/);
  assert.match(label, /UTC/);
  assert.doesNotMatch(chartFollowStatusLabel({ state: "connecting", latestBarMs: null }), /UTC|—/);
  assert.equal(chartFollowStatusTone("live"), "live");
  assert.equal(chartFollowStatusTone("connecting"), "running");
  assert.equal(chartFollowStatusTone("waiting"), "stale");
});
