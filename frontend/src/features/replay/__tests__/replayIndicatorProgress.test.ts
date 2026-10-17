import assert from "node:assert/strict";
import test from "node:test";
import { ReplayIndicatorProgress, replayIndicatorPreparationFraction } from "../replayIndicatorProgress.js";

test("display progress measures completed prefix duration instead of Unix timestamps or trade counts", () => {
  const origin = 1_600_000_000_000;
  assert.equal(replayIndicatorPreparationFraction(origin, origin + 250, origin + 1000), 0.25);
  assert.equal(replayIndicatorPreparationFraction(origin, origin, origin + 1000), 0);
  for (const [start, before, end] of [[undefined, origin, origin + 1000], [origin, 25, 100],
    [origin, origin - 1, origin + 1000], [origin, origin + 1000, origin + 1000], [0, Infinity, 100]]) {
    assert.equal(replayIndicatorPreparationFraction(start, before, end), null);
  }
});

const pending = (before: number, phase: "context" | "trades", prepared: number, target: number) => ({
  prepared_before_ms: before, target_before_ms: 1000,
  source_preparation: { window_start_ms: before, window_stop_ms: before + 100,
    phase, prepared, target, source_sequence: 50 },
});

test("one bucket can prepare multiple context and trade pages before math advances", () => {
  const state = new ReplayIndicatorProgress();
  for (const row of [pending(0, "context", 20, 100), pending(0, "context", 80, 100),
    pending(0, "trades", 1, 25), pending(0, "trades", 17, 25)]) {
    assert.equal(state.advance(row, 1000, 50).phase, "history");
  }
  assert.deepEqual(state.advance({ prepared_before_ms: 100, target_before_ms: 1000 }, 1000, 50),
    { phase: "prefix", prepared: 100, target: 1000 });
  assert.equal(state.advance(pending(100, "context", 120, 200), 1000, 50).phase, "history");
});

test("stalls, phase regressions, changed windows and source sequences are rejected", () => {
  const first = pending(0, "trades", 10, 25);
  for (const row of [first, pending(0, "trades", 9, 25), pending(0, "context", 20, 100),
    pending(0, "trades", 11, 26), { ...first, source_preparation: { ...first.source_preparation, window_stop_ms: 101 } },
    { ...first, source_preparation: { ...first.source_preparation, source_sequence: 51 } },
    { prepared_before_ms: 0, target_before_ms: 1000 }]) {
    const state = new ReplayIndicatorProgress(); state.advance(first, 1000, 50);
    assert.throws(() => state.advance(row, 1000, 50));
  }
  assert.throws(() => new ReplayIndicatorProgress().advance(first, 1000));
  assert.throws(() => new ReplayIndicatorProgress().advance(pending(0, "trades", 25, 25), 1000, 50));
  assert.throws(() => new ReplayIndicatorProgress().advance(pending(0, "context", 20, 101), 1000, 50));
});
