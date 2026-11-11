import assert from "node:assert/strict";
import test from "node:test";
import { ApiError } from "../../../services/api.js";
import { ApiPayloadError } from "../../../services/apiPayloadParsers.js";

import {
  LIQUIDATION_HISTORY_RETRY_DELAY_MS,
  LiquidationHistoryRequestCoordinator,
  LiquidationHistoryRetryBudget,
  liquidationHistoryRangeForCandles,
  normalizeLiquidationHistoryRange,
  subtractLiquidationHistoryCoverage,
  subtractLiquidationHistoryRanges,
} from "../liquidationHistoryRequests.js";

test("permanent rejection and invalid history payload stop automatic requests", () => {
  for (const error of [
    new ApiError({ status: 422, detail: "Unsupported market", code: null, url: "/liquidations/history" }),
    new ApiPayloadError("next_cursor", "Invalid cursor"),
  ]) {
    const budget = new LiquidationHistoryRetryBudget();
    assert.equal(budget.failed(error, 0), false);
    assert.equal(budget.canRequest(300_000), false);
    assert.equal(budget.succeeded(300_000), false);
  }
});

test("rate limiting allows two delayed retries and does not consume a retry for parallel failures", () => {
  const delay = LIQUIDATION_HISTORY_RETRY_DELAY_MS;
  const budget = new LiquidationHistoryRetryBudget();
  const error = new ApiError({ status: 429, detail: "Rate limited", code: null, url: "/liquidations/history" });
  assert.equal(budget.failed(error, 0), true);
  assert.equal(budget.failed(error, 1), false);
  assert.equal(budget.canRequest(delay - 1), false);
  assert.equal(budget.canRequest(delay), true);
  assert.equal(budget.failed(error, delay), true);
  assert.equal(budget.failed(error, delay * 2), false);
  assert.equal(budget.canRequest(delay * 10), false);

  const recovered = new LiquidationHistoryRetryBudget();
  assert.equal(recovered.failed(error, 0), true);
  assert.equal(recovered.succeeded(delay), true);
  assert.equal(recovered.failed(error, delay + 1), true);
  assert.equal(recovered.failed(error, delay * 2 + 1), true);
});

test("forming hourly candle history reaches now instead of its opening minute", () => {
  const open = Date.UTC(2026, 9, 2, 10);
  const now = open + 40 * 60_000;
  assert.deepEqual(liquidationHistoryRangeForCandles(open / 1000, open / 1000, "1h", now), {
    startMs: open, endMs: now,
  });
});

test("closed last candle and calendar month include the entire final bucket", () => {
  const open = Date.UTC(2026, 0, 1);
  const nextMonth = Date.UTC(2026, 1, 1);
  assert.deepEqual(liquidationHistoryRangeForCandles(open / 1000, open / 1000, "1M", nextMonth + 1), {
    startMs: open, endMs: nextMonth - 1,
  });
  assert.deepEqual(liquidationHistoryRangeForCandles(open / 1000, open / 1000, "1h", nextMonth), {
    startMs: open, endMs: open + 3_600_000 - 1,
  });
  assert.equal(liquidationHistoryRangeForCandles(nextMonth / 1000, nextMonth / 1000, "1h", open), null);
});

test("bulk coverage eviction handles 5000 fragmented segments and gaps spanning segments", () => {
  const coverage = Array.from({ length: 5000 }, (_, index) => ({ startMs: index * 10, endMs: index * 10 + 5 }));
  const removed = Array.from({ length: 5000 }, (_, index) => ({ startMs: index * 10 + 3, endMs: index * 10 + 8 }));
  assert.deepEqual(subtractLiquidationHistoryRanges(coverage, removed),
    coverage.map((range) => ({ startMs: range.startMs, endMs: range.startMs + 2 })));
  assert.deepEqual(subtractLiquidationHistoryRanges(coverage.slice(0, 3), [{ startMs: 3, endMs: 22 }]), [
    { startMs: 0, endMs: 2 }, { startMs: 23, endMs: 25 },
  ]);
});

test("future-only ranges fail closed before any history claim can be created", () => {
  const nowMs = 1_700_000_000_000;
  const requested = normalizeLiquidationHistoryRange({
    startMs: nowMs + 1,
    endMs: nowMs + 120_000,
  }, nowMs);
  assert.equal(requested, null);

  const coordinator = new LiquidationHistoryRequestCoordinator();
  if (requested) coordinator.claim("long", requested, []);
  assert.deepEqual(coordinator.inFlight("long"), []);
});

test("ranges crossing now include the current partial minute without covering the future", () => {
  const nowMs = 1_700_000_012_345;
  const requested = normalizeLiquidationHistoryRange({
    startMs: nowMs - 61_234,
    endMs: nowMs + 120_000,
  }, nowMs);

  assert.deepEqual(requested, {
    startMs: Math.floor((nowMs - 61_234) / 60_000) * 60_000,
    endMs: nowMs,
  });
});

test("coverage subtraction returns every gap around an occupied middle interval", () => {
  assert.deepEqual(
    subtractLiquidationHistoryCoverage(
      { startMs: 0, endMs: 299 },
      [{ startMs: 100, endMs: 199 }],
    ),
    [
      { startMs: 0, endMs: 99 },
      { startMs: 200, endMs: 299 },
    ],
  );
});

test("overlapping viewport requests claim only ranges not already in flight", () => {
  const coordinator = new LiquidationHistoryRequestCoordinator();
  const first = coordinator.claim("long", { startMs: 0, endMs: 199 }, []);
  const second = coordinator.claim("long", { startMs: 100, endMs: 299 }, []);

  assert.deepEqual(first.map((claim) => claim.range), [{ startMs: 0, endMs: 199 }]);
  assert.deepEqual(second.map((claim) => claim.range), [{ startMs: 200, endMs: 299 }]);
  assert.deepEqual(coordinator.inFlight("long"), [
    { startMs: 0, endMs: 199 },
    { startMs: 200, endMs: 299 },
  ]);
});

test("durable and in-flight ranges are subtracted together without hiding later gaps", () => {
  const coordinator = new LiquidationHistoryRequestCoordinator();
  coordinator.claim("short", { startMs: 100, endMs: 199 }, []);

  const claims = coordinator.claim(
    "short",
    { startMs: 0, endMs: 299 },
    [{ startMs: 0, endMs: 49 }],
  );

  assert.deepEqual(claims.map((claim) => claim.range), [
    { startMs: 50, endMs: 99 },
    { startMs: 200, endMs: 299 },
  ]);
});

test("claims are isolated by side and become retryable after release or clear", () => {
  const coordinator = new LiquidationHistoryRequestCoordinator();
  const [longClaim] = coordinator.claim("long", { startMs: 0, endMs: 99 }, []);
  assert.ok(longClaim);
  assert.deepEqual(
    coordinator.claim("short", { startMs: 0, endMs: 99 }, []).map((claim) => claim.range),
    [{ startMs: 0, endMs: 99 }],
  );
  assert.deepEqual(coordinator.claim("long", { startMs: 0, endMs: 99 }, []), []);

  coordinator.release(longClaim);
  assert.deepEqual(
    coordinator.claim("long", { startMs: 0, endMs: 99 }, []).map((claim) => claim.range),
    [{ startMs: 0, endMs: 99 }],
  );
  coordinator.clear();
  assert.deepEqual(coordinator.inFlight("long"), []);
  assert.deepEqual(coordinator.inFlight("short"), []);
});
