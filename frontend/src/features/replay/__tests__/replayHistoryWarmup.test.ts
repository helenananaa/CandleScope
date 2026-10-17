import assert from "node:assert/strict";
import test from "node:test";
import { replayHistoryNeedsWarmup, replayHistoryWarmupTarget } from "../replayHistoryWarmup.js";

test("small remote pages keep warming visible studies until their output window is present", () => {
  const target = replayHistoryWarmupTarget([{ id: "sma", engineName: "SMA", params: { period: 20 } }]);
  assert.equal(target, 20);
  const idle = { targetBars: target, hasMore: true, loading: false, error: null, rightTruncated: false };
  assert.deepEqual([6, 11, 16, 21].map(barCount => replayHistoryNeedsWarmup({ ...idle, barCount })),
    [true, true, true, false]);
  assert.equal(replayHistoryNeedsWarmup({ ...idle, barCount: 6, loading: true }), false);
  assert.equal(replayHistoryNeedsWarmup({ ...idle, barCount: 6, hasMore: false }), false);
  assert.equal(replayHistoryNeedsWarmup({ ...idle, barCount: 6, error: "download failed" }), false);
  assert.equal(replayHistoryNeedsWarmup({ ...idle, barCount: 6, rightTruncated: true }), false);
});

test("warmup uses existing recursive and script estimates, ignores hidden studies and is bounded", () => {
  assert.equal(replayHistoryWarmupTarget([]), 0);
  assert.equal(replayHistoryWarmupTarget([{ id: "ma", engineName: "SMA", visible: false }]), 0);
  assert.equal(replayHistoryWarmupTarget([{ id: "ema", engineName: "EMA", params: { period: 20 } }]), 101);
  assert.equal(replayHistoryWarmupTarget([{ id: "pine", engineName: "PINE" }]), 201);
  assert.equal(replayHistoryWarmupTarget([{ id: "pine", engineName: "PINE", params: { warmup: 30 } }]), 31);
  assert.equal(replayHistoryWarmupTarget([{ id: "ma", engineName: "SMA", params: { period: 1e9 } }]), 2000);
});
