import assert from "node:assert/strict";
import test from "node:test";

import {
  clampHistoryRangeToNow,
  coverageForHistoryPage,
  coverageRangesForHistoryPage,
  HistoryGapRetryBudget,
  mergeHistoryCoverage,
  nextUncoveredHistoryRange,
  OpenInterestHistoryRetryBudget,
  openInterestSampleCells,
  observationHistoryWindowKey,
} from "../marketHistoryCoverage.js";

test("explicit committed ranges preserve holes even on short pages or partial failures", () => {
  const requested = { startMs: 1000, endMs: 9000 };
  const payload = {
    count: 2, complete: false, has_more: false, retryable: true,
    coverage: { earliest_ms: 1000, latest_ms: 8000, complete: false,
      ranges: [{ start_ms: 1000, end_ms: 1999 }, { start_ms: 8000, end_ms: 9000 }] },
  };
  const ranges = coverageRangesForHistoryPage(requested, payload, "backward");
  assert.deepEqual(nextUncoveredHistoryRange(ranges, requested), { startMs: 2000, endMs: 7999 });
  assert.equal(coverageForHistoryPage(requested, payload, "backward"), null);
  assert.deepEqual(coverageRangesForHistoryPage(requested, { ...payload,
    excluded_ranges: [{ start_ms: 2000, end_ms: 7999, reason: "outside_upstream_retention" }],
  }, "backward"), [requested]);
});

test("unknown empty native pages do not cause unlimited automatic retries", () => {
  const budget = new HistoryGapRetryBudget();
  assert.equal(budget.fail("empty"), true);
  assert.equal(budget.fail("empty"), true);
  assert.equal(budget.fail("empty"), false);
  assert.equal(budget.blocked("empty"), true);
  assert.equal(budget.blocked("other"), false);
  budget.clear();
  assert.equal(budget.blocked("empty"), false);
});

test("a moving OI tail shares one sample budget without blocking the next cell", () => {
  const budget = new OpenInterestHistoryRetryBudget();
  const step = 300_000;
  const gap = { startMs: step, endMs: step };
  const cell = { startMs: step, endMs: 2 * step - 1 };
  const moving = { startMs: step, endMs: step + 12_000 };
  assert.deepEqual(openInterestSampleCells(gap, step), cell);
  assert.deepEqual(openInterestSampleCells(moving, step), cell);
  assert.equal(openInterestSampleCells({ startMs: step + 1, endMs: moving.endMs }, step), null);
  assert.equal(budget.fail(gap, step, 1_000, 30_000), true);
  assert.deepEqual(budget.deferred(moving, step, 1_100), { ranges: [cell], retryAt: 31_000 });
  assert.equal(nextUncoveredHistoryRange(budget.deferred(moving, step, 1_100).ranges, moving), null);
  assert.equal(nextUncoveredHistoryRange(budget.deferred(moving, step, 31_000).ranges, moving)?.startMs, step);
  assert.equal(budget.fail(moving, step, 31_000, 30_000), true);
  assert.equal(budget.fail(moving, step, 61_000, 30_000), false);
  assert.deepEqual(budget.deferred(moving, step, 1_000_000), { ranges: [cell], retryAt: null });

  const next = { startMs: 2 * step, endMs: 2 * step + 700 };
  assert.deepEqual(budget.deferred(next, step, 1_000_000), { ranges: [], retryAt: null });
  assert.deepEqual(nextUncoveredHistoryRange(budget.deferred(moving, step, 1_000_000).ranges, {
    startMs: moving.startMs, endMs: next.endMs,
  }), next);
  budget.accept([{ start_ms: cell.startMs, end_ms: cell.endMs }]);
  assert.equal(budget.fail(gap, step, 1_000_001, 30_000), true);
  budget.clear();
  assert.deepEqual(budget.deferred(moving, step, 1_000_002), { ranges: [], retryAt: null });
});

test("observation windows coalesce a moving edge without satisfying any coverage", () => {
  const range = { startMs: 300_000, endMs: 600_000 };
  assert.equal(observationHistoryWindowKey(range, 300_000),
    observationHistoryWindowKey({ ...range, endMs: 608_000 }, 300_000));
  assert.notEqual(observationHistoryWindowKey(range, 300_000),
    observationHistoryWindowKey({ ...range, endMs: 900_000 }, 300_000));
  assert.deepEqual(coverageRangesForHistoryPage(range, {
    count: 1, complete: false, has_more: false,
    coverage: { earliest_ms: 300_000, latest_ms: 300_000, complete: false,
      ranges: [], basis: "observations_only" },
  }, "backward"), []);
});

test("future-only market history ranges are not requested", () => {
  assert.equal(clampHistoryRangeToNow({ startMs: 2_001, endMs: 3_000 }, 2_000), null);
});

test("market history ranges crossing now are clamped to the current time", () => {
  assert.deepEqual(
    clampHistoryRangeToNow({ startMs: 1_000, endMs: 3_000 }, 2_000),
    { startMs: 1_000, endMs: 2_000 },
  );
});

test("a full finite page advances the next request to the older uncovered range", () => {
  const requested = { startMs: 1_000, endMs: 10_000 };
  const first = coverageForHistoryPage(requested, {
    count: 500,
    coverage: { earliest_ms: 6_000, latest_ms: 10_000, complete: false },
    has_more: true,
    fallback: false,
  }, "backward");
  assert.deepEqual(first, { startMs: 6_000, endMs: 10_000 });
  assert.deepEqual(
    nextUncoveredHistoryRange([first], requested),
    { startMs: 1_000, endMs: 5_999 },
  );

  const secondRequest = { startMs: 1_000, endMs: 5_999 };
  const second = coverageForHistoryPage(secondRequest, {
    count: 500,
    coverage: { earliest_ms: 2_000, latest_ms: 5_999, complete: false },
    has_more: true,
    fallback: false,
  }, "backward");
  assert.ok(second);
  const coverage = mergeHistoryCoverage([first], second);
  assert.deepEqual(
    nextUncoveredHistoryRange(coverage, requested),
    { startMs: 1_000, endMs: 1_999 },
  );
});

test("Funding full pages advance forward from the oldest page", () => {
  const requested = { startMs: 1_000, endMs: 10_000 };
  const covered = coverageForHistoryPage(requested, {
    count: 1_000,
    coverage: { earliest_ms: 1_000, latest_ms: 6_000, complete: false },
    has_more: true,
    fallback: false,
  }, "forward");
  assert.deepEqual(covered, { startMs: 1_000, endMs: 6_000 });
  assert.deepEqual(
    nextUncoveredHistoryRange(covered ? [covered] : [], requested),
    { startMs: 6_001, endMs: 10_000 },
  );
});

test("explicitly complete pages close the request while fallback stays retryable", () => {
  const requested = { startMs: 1_000, endMs: 5_000 };
  const shortPage = coverageForHistoryPage(requested, {
    count: 12,
    coverage: { earliest_ms: 2_000, latest_ms: 4_000, complete: true },
    has_more: false,
    fallback: false,
  }, "backward");
  assert.deepEqual(shortPage, requested);
  assert.equal(nextUncoveredHistoryRange(shortPage ? [shortPage] : [], requested), null);

  const fallbackPage = coverageForHistoryPage(requested, {
    count: 12,
    coverage: { earliest_ms: 2_000, latest_ms: 4_000, complete: false },
    has_more: true,
    fallback: true,
  }, "backward");
  assert.equal(fallbackPage, null);
  assert.deepEqual(nextUncoveredHistoryRange([], requested), requested);
});

test("partial retryable hybrid pages render data without claiming coverage", () => {
  const requested = { startMs: 1_000, endMs: 10_000 };
  const partial = coverageForHistoryPage(requested, {
    count: 48,
    coverage: { earliest_ms: 1_000, latest_ms: 8_000, complete: false },
    has_more: false,
    fallback: false,
    history_state: "pending",
    complete: false,
    retryable: true,
  }, "forward");

  assert.equal(partial, null);
  assert.deepEqual(nextUncoveredHistoryRange([], requested), requested);
});

test("terminal empty pages become resolved coverage instead of a retry loop", () => {
  const requested = { startMs: 1_000, endMs: 5_000 };
  const exhausted = coverageForHistoryPage(requested, {
    count: 0,
    coverage: { earliest_ms: null, latest_ms: null, complete: false },
    fallback: false,
    history_state: "exhausted",
    complete: true,
    retryable: false,
  }, "backward");

  assert.deepEqual(exhausted, requested);
  assert.equal(nextUncoveredHistoryRange(exhausted ? [exhausted] : [], requested), null);

  const exhaustedFallback = coverageForHistoryPage(requested, {
    count: 0,
    coverage: { earliest_ms: null, latest_ms: null, complete: false },
    fallback: true,
    history_state: "exhausted",
    complete: true,
    retryable: false,
  }, "backward");
  assert.deepEqual(exhaustedFallback, requested);

  const pending = coverageForHistoryPage(requested, {
    count: 0,
    coverage: { earliest_ms: null, latest_ms: null, complete: false },
    fallback: false,
    history_state: "pending",
    complete: false,
    retryable: true,
  }, "backward");
  assert.equal(pending, null);

  const incompleteNonRetryable = coverageForHistoryPage(requested, {
    count: 0,
    coverage: { earliest_ms: null, latest_ms: null, complete: false },
    fallback: false,
    has_more: true,
    history_state: "ready",
    complete: false,
    retryable: false,
  }, "forward");
  assert.equal(incompleteNonRetryable, null);
  assert.deepEqual(nextUncoveredHistoryRange([], requested), requested);
});

test("coverage segments preserve real gaps instead of claiming one broad span", () => {
  const coverage = mergeHistoryCoverage(
    [{ startMs: 1_000, endMs: 2_000 }],
    { startMs: 4_000, endMs: 5_000 },
  );
  assert.deepEqual(
    nextUncoveredHistoryRange(coverage, { startMs: 1_000, endMs: 5_000 }),
    { startMs: 2_001, endMs: 3_999 },
  );
});
