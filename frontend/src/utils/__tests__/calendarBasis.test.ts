import assert from "node:assert/strict";
import { test } from "node:test";
import { calendarParts, calendarWallToUtc } from "../calendarBasis.js";
import { createIntervalTimeline, createFutureIntervalBasis, futureTimeFromIntervalDistance, futureIntervalDistanceFromTime } from "../intervalTimeline.js";
import { canResolveIntervalFromNativeValues, intervalSemanticSignature } from "../intervals.js";

const time = (value: string) => Date.parse(value) / 1000;
for (const [start, end] of [["2024-03-10T05:00Z", "2024-03-11T04:00Z"], ["2024-11-03T04:00Z", "2024-11-04T05:00Z"]]) {
  test(`New York calendar day ${start}`, () => {
    const interval = "1d~c1~America/New_York";
    const timeline = createIntervalTimeline(interval)!;
    assert.equal(timeline.floor(time(end!) - 1), time(start!));
    assert.equal(timeline.next(time(start!)), time(end!));
    assert.equal(timeline.previous(time(end!)), time(start!));
    const basis = createFutureIntervalBasis({ sourceInterval: interval, horizon: time(start!) })!;
    for (const distance of [0.5, 1, 1.25, 10, 400]) {
      const future = futureTimeFromIntervalDistance(basis, distance)!;
      assert.equal(futureIntervalDistanceFromTime(basis, future), distance);
    }
  });
}
test("calendar contract rejects ambiguous local times and inexact sources", () => {
  assert.equal(calendarWallToUtc(time("2024-03-10T02:30Z"), "America/New_York"), null);
  assert.equal(calendarWallToUtc(time("2024-11-03T01:30Z"), "America/New_York"), null);
  assert.equal(calendarParts("24h~c1~UTC"), null);
  assert.equal(canResolveIntervalFromNativeValues("1d~c1~America/New_York", ["2h", "1d"]), false);
  assert.equal(canResolveIntervalFromNativeValues("1d~c1~America/New_York", ["1h"]), true);
  assert.notEqual(intervalSemanticSignature("1d~c1~UTC"), intervalSemanticSignature("1d"));
});

test("local calendar composition and request budget include the DST long day", async () => {
  const { resolveLocalIntervalSupport } = await import("../../features/local-data/localIntervalPolicy.js");
  const { planTargetBarRequest } = await import("../../features/market-data/intervalRequestBudget.js");
  const interval = "1d~c1~America/New_York";
  assert.equal(resolveLocalIntervalSupport({ interval: "1h", alignment_offset_ms: 0 }, interval).supported, true);
  assert.equal(resolveLocalIntervalSupport({ interval: "2h", alignment_offset_ms: 0 }, interval).supported, false);
  assert.equal(resolveLocalIntervalSupport({ interval, alignment_offset_ms: 0 }, "2d~c1~America/New_York").supported, false);
  const plan = planTargetBarRequest({ interval, nativeIntervals: ["1h"], desiredTargetBars: 100, sourceRowBudget: 1000 });
  assert.ok(plan.sourceFactor >= 25);
  assert.ok(plan.estimatedSourceRows <= 1000);
});
