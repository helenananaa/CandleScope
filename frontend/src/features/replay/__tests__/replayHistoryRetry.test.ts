import assert from "node:assert/strict";
import test from "node:test";
import { replayHistoryRetryDelay } from "../replayHistoryRetry.js";

test("market cache pressure retries only when declared temporary and stops after two retries", () => {
  const delays = [500, 1_000, 2_000];
  const busy = { code: "HISTORY_CACHE_BUSY", details: { retryable: true } };
  assert.equal(replayHistoryRetryDelay(busy, 0, delays), 500);
  assert.equal(replayHistoryRetryDelay(busy, 1, delays), 1_000);
  assert.equal(replayHistoryRetryDelay(busy, 2, delays), undefined);
  for (const details of [undefined, {}, { retryable: false }, { retryable: "true" }]) {
    assert.equal(replayHistoryRetryDelay({ code: busy.code, details }, 0, delays), undefined);
  }
  for (const code of ["INPUT_CORRUPT", "HISTORY_SOURCE_INCOMPLETE", "UNKNOWN_ERROR"]) {
    assert.equal(replayHistoryRetryDelay({ ...busy, code }, 0, delays), undefined);
  }
});
