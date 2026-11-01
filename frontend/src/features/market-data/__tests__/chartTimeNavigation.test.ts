import assert from "node:assert/strict";
import test from "node:test";
import { locateChartTime, planChartTimeSeek } from "../chartTimeNavigation.js";
import type { KlineBar } from "../marketDataTypes.js";
import { epochSeconds } from "../../../test/testHelpers.js";

const ms = (text: string) => Date.parse(text);
const rows = (...times: number[]): KlineBar[] => times.map(time => ({ time: epochSeconds(time) }));

test("date navigation fetches around the containing bar, without walking from now", () => {
  const target = ms("2024-02-10T12:04:59Z");
  const plan = planChartTimeSeek("1m", target, ms("2026-01-01T00:00:00Z"), 5)!;
  assert.equal(plan.start, ms("2024-02-10T12:02:00Z") / 1000);
  assert.equal(plan.end, ms("2024-02-10T12:06:00Z") / 1000);
  assert.deepEqual(locateChartTime(rows(plan.bucketTime, plan.bucketTime + 60), plan), {
    status: "located", requestedTimeMs: target, actualTimeMs: plan.bucketTime * 1000, exact: true,
  });
});

test("calendar months retain real month boundaries across February", () => {
  const plan = planChartTimeSeek("1M", ms("2024-02-29T15:00:00Z"), ms("2025-01-01T00:00:00Z"), 3)!;
  assert.equal(plan.start, ms("2024-01-01T00:00:00Z") / 1000);
  assert.equal(plan.bucketTime, ms("2024-02-01T00:00:00Z") / 1000);
  assert.equal(plan.end, ms("2024-03-01T00:00:00Z") / 1000);
});

test("live seek rejects future/invalid requests and clips its window to now", () => {
  const now = ms("2024-02-10T12:04:40Z");
  assert.equal(planChartTimeSeek("1m", now + 1, now), null);
  assert.equal(planChartTimeSeek("1m", Number.NaN, now), null);
  assert.equal(planChartTimeSeek("invalid", now, now), null);
  assert.equal(planChartTimeSeek("1m", now, now, 100_000), null);
  const plan = planChartTimeSeek("1m", now, now, 5)!;
  assert.equal(plan.end, plan.bucketTime);
});

test("gaps report an actual nearby bar and ties prefer the earlier bar", () => {
  const plan = planChartTimeSeek("1m", ms("2024-02-10T12:04:00Z"), ms("2025-01-01T00:00:00Z"), 5)!;
  const result = locateChartTime(rows(plan.bucketTime - 60, plan.bucketTime + 60), plan)!;
  assert.equal(result.actualTimeMs, (plan.bucketTime - 60) * 1000);
  assert.equal(result.exact, false);
  assert.equal(locateChartTime([], plan), null);
});

test("unbounded, unordered, duplicate and invalid response rows cannot locate a chart", () => {
  const plan = planChartTimeSeek("1m", ms("2024-02-10T12:04:00Z"), ms("2025-01-01T00:00:00Z"), 5)!;
  assert.equal(locateChartTime(rows(plan.start - 60, plan.bucketTime), plan), null);
  assert.equal(locateChartTime(rows(plan.bucketTime, plan.end + 60), plan), null);
  assert.equal(locateChartTime(rows(plan.bucketTime + 60, plan.bucketTime), plan), null);
  assert.equal(locateChartTime(rows(plan.bucketTime, plan.bucketTime), plan), null);
});
