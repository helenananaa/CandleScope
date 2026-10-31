import assert from "node:assert/strict";
import test from "node:test";
import type { KlineStreamControlMessage } from "../klineContracts.js";

import {
  acknowledgeKlineStreamInterval,
  createKlineStreamAcknowledgementState,
  getKlineStreamIntervalStatus,
  planKlineRecoveryCountBack,
  planHeldKlineRecoveryCountBack,
  reduceKlineStreamControlMessage,
  retainTrackedKlineStreamRejections,
  WS_KLINE_FRESHNESS_MS,
} from "../useKlineStreamRuntime.js";

test("stream recovery shares the bounded derived-history policy", () => {
  const nativeIntervals = ["1m", "3m", "5m", "15m", "30m", "1h"];

  assert.equal(planKlineRecoveryCountBack("1m", nativeIntervals), 1_500);
  assert.equal(planKlineRecoveryCountBack("91m", nativeIntervals), 216);
  assert.equal(planKlineRecoveryCountBack("91m", nativeIntervals, 50), 50);
  assert.equal(planKlineRecoveryCountBack("10001m", nativeIntervals), 0);
});

test("reconnect retains staged custom history depth instead of requesting full history", () => {
  const nativeIntervals = ["1m", "15m", "30m", "1d", "2d", "3d"];
  for (const interval of ["45m", "90m", "4d", "5d"]) {
    assert.equal(planHeldKlineRecoveryCountBack(interval, nativeIntervals, 0), 128);
    assert.equal(planHeldKlineRecoveryCountBack(interval, nativeIntervals, 112), 128);
    assert.equal(planHeldKlineRecoveryCountBack(interval, nativeIntervals, 500), 500);
    assert.equal(planHeldKlineRecoveryCountBack(interval, nativeIntervals, 1500), 1500);
  }
  assert.equal(planHeldKlineRecoveryCountBack("1m", nativeIntervals, 0), 500);
  assert.equal(planHeldKlineRecoveryCountBack("10001m", nativeIntervals, 1500), 0);
});

test("socket open remains connecting before any interval is acknowledged", () => {
  const state = createKlineStreamAcknowledgementState();

  assert.equal(getKlineStreamIntervalStatus(state, "1m"), "connecting");
});

test("mixed subscription ACK activates only accepted intervals and rejects failures", () => {
  const state = reduceKlineStreamControlMessage(
    createKlineStreamAcknowledgementState(),
    {
      type: "subscribed",
      request_id: "request-1",
      requested_intervals: ["1m", "7s"],
      intervals: ["1m"],
      failed: [{ interval: "7s", code: "unsupported_interval" }],
      active_intervals: ["1m"],
    },
  );

  assert.deepEqual(state.activeIntervals, ["1m"]);
  assert.deepEqual(state.rejectedIntervals, ["7s"]);
  assert.equal(getKlineStreamIntervalStatus(state, "1m"), "loading");
  assert.equal(getKlineStreamIntervalStatus(state, "7s"), "fallback");
});

test("a first valid current-interval kline confirms legacy backends", () => {
  const state = acknowledgeKlineStreamInterval(
    createKlineStreamAcknowledgementState(),
    "47m",
  );

  assert.equal(getKlineStreamIntervalStatus(state, "47m"), "live");
});

test("ACK state treats fixed-duration aliases as the same interval", () => {
  const state = reduceKlineStreamControlMessage(
    createKlineStreamAcknowledgementState(),
    {
      type: "subscribed",
      requested_intervals: ["60m"],
      intervals: ["1h"],
      failed: [],
      active_intervals: ["1h"],
    },
  );

  assert.equal(getKlineStreamIntervalStatus(state, "60m"), "loading");
  const observed = acknowledgeKlineStreamInterval(state, "60m", 10_000);
  assert.equal(getKlineStreamIntervalStatus(observed, "1h", 10_001), "live");
});

test("local ACK and repeated ACK cannot make silent upstream data live", () => {
  const ack: KlineStreamControlMessage = {
    type: "subscribed", intervals: ["1m", "1h"], active_intervals: ["1m", "1h"],
  };
  let state = reduceKlineStreamControlMessage(createKlineStreamAcknowledgementState(), ack);
  assert.equal(getKlineStreamIntervalStatus(state, "1h", 10_000), "loading");
  state = acknowledgeKlineStreamInterval(state, "1m", 10_000);
  assert.equal(getKlineStreamIntervalStatus(state, "1h", 10_001), "loading");
  assert.equal(getKlineStreamIntervalStatus(state, "1m", 10_001), "live");
  state = reduceKlineStreamControlMessage(state, ack);
  assert.equal(getKlineStreamIntervalStatus(state, "1m", 10_000 + WS_KLINE_FRESHNESS_MS), "loading");
  state = acknowledgeKlineStreamInterval(state, "1m", 100_000);
  assert.equal(getKlineStreamIntervalStatus(state, "1m", 100_001), "live");
});

test("unsubscribe and rejection discard previous freshness before resubscription", () => {
  const observed = acknowledgeKlineStreamInterval(createKlineStreamAcknowledgementState(), "1h", 10_000);
  const messages: KlineStreamControlMessage[] = [
    { type: "unsubscribed", intervals: ["1h"], active_intervals: [] },
    { type: "subscribed", intervals: [], failed: [{ interval: "1h" }], active_intervals: [] },
  ];
  for (const message of messages) {
    const removed = reduceKlineStreamControlMessage(observed, message);
    const resubscribed = reduceKlineStreamControlMessage(removed,
      { type: "subscribed", intervals: ["1h"], active_intervals: ["1h"] });
    assert.equal(getKlineStreamIntervalStatus(resubscribed, "1h", 10_001), "loading");
  }
});

test("unsubscribed current intervals wait for a new ACK and removed failures can retry", () => {
  const rejected = reduceKlineStreamControlMessage(
    createKlineStreamAcknowledgementState(),
    {
      type: "subscribed",
      requested_intervals: ["7s"],
      intervals: [],
      failed: [{ interval: "7s" }],
      active_intervals: [],
    },
  );
  const removed = retainTrackedKlineStreamRejections(rejected, ["1m"]);
  assert.equal(getKlineStreamIntervalStatus(removed, "7s"), "connecting");

  const live = reduceKlineStreamControlMessage(
    createKlineStreamAcknowledgementState(),
    { type: "subscribed", intervals: ["1m"], active_intervals: ["1m"] },
  );
  const unsubscribed = reduceKlineStreamControlMessage(live, {
    type: "unsubscribed",
    intervals: ["1m"],
    active_intervals: [],
  });
  assert.equal(getKlineStreamIntervalStatus(unsubscribed, "1m"), "connecting");
});
