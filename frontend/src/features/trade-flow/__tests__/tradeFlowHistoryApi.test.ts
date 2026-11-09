import assert from "node:assert/strict";
import test from "node:test";
import { fillTradeHistory, readTradeHistory, supportsTradeHistoryArchive } from "../tradeFlowHistoryApi.js";

const identity = { exchange: "binance", marketType: "futures", symbol: "LTCUSDT" };
const start = Date.UTC(2026, 9, 1, 4);

test("opening the selected UTC hour reads one local page and keeps server coverage separate", async (context) => {
  const page = { data: [{ bucket_start_ms: start, is_complete: true, is_final: true }], complete: false, has_more: false };
  const signal = new AbortController().signal;
  const fetch = context.mock.method(globalThis, "fetch", async (input: string, init: RequestInit) => {
    assert.equal(init.method, undefined);
    assert.equal(init.signal, signal);
    const url = new URL(input, "http://localhost");
    assert.ok(url.pathname.endsWith("/trade-flow/history"));
    assert.deepEqual(Object.fromEntries(url.searchParams), {
      exchange: "binance", market_type: "futures", symbol: "LTCUSDT",
      start_ms: String(start), end_ms: String(start + 59 * 60_000), limit: "60",
    });
    return Response.json(page);
  });
  assert.deepEqual(await readTradeHistory(identity, start, signal), page);
  assert.equal(fetch.mock.callCount(), 1);
});

test("the explicit archive action reuses the submission key and resumes an eligible durable job", async (context) => {
  const signal = new AbortController().signal;
  const key = "same-trade-request";
  const states: string[] = [];
  const fetch = context.mock.method(globalThis, "fetch", async (input: string, init: RequestInit) => {
    assert.equal(init.method, "POST");
    assert.equal(init.signal, signal);
    if (input.endsWith("/trade-flow-history")) {
      assert.deepEqual(JSON.parse(String(init.body)), {
        exchange: "binance", market_type: "futures", symbol: "LTCUSDT",
        start_ms: start, end_ms: start + 59 * 60_000, idempotency_key: key,
      });
      return Response.json({ status: "preparation", job: {
        id: "durable-job", state: "FAILED", error: { retryable: true }, cancel_requested: false,
      } });
    }
    assert.ok(input.endsWith("/durable-job/retry"));
    return Response.json({ id: "durable-job", state: "READY" });
  });
  assert.equal(await fillTradeHistory(identity, start, key, (job) => states.push(job.state), signal), "readback");
  assert.deepEqual(states, ["READY"]);
  assert.equal(fetch.mock.callCount(), 2);
});

test("an unpublished archive day schedules no polling or retry", async (context) => {
  const fetch = context.mock.method(globalThis, "fetch", async () => Response.json({
    status: "unavailable", job: null,
  }));
  const result = await fillTradeHistory(identity, start, "published-check", () => assert.fail("No job expected"),
    new AbortController().signal);
  assert.equal(result, "unavailable");
  assert.equal(fetch.mock.callCount(), 1);
  assert.equal(supportsTradeHistoryArchive(identity), true);
  assert.equal(supportsTradeHistoryArchive({ ...identity, marketType: "spot" }), false);
  assert.equal(supportsTradeHistoryArchive({ ...identity, exchange: "okx" }), false);
});

test("a retained archive without verified minute coverage requests a local readback", async (context) => {
  const fetch = context.mock.method(globalThis, "fetch", async () => Response.json({
    status: "projection_unverified", job: null,
    unavailable_ranges: [{ reason: "trade_archive_projection_unverified" }],
  }));
  const result = await fillTradeHistory(identity, start, "retained-check", () => assert.fail("No job expected"),
    new AbortController().signal);
  assert.equal(result, "readback");
  assert.equal(fetch.mock.callCount(), 1);
});
