import assert from "node:assert/strict";
import test from "node:test";
import type { TransportKlineResponse } from "../../services/apiPayloadParsers.js";
import { loadReplayBars, ReplayHistoryPendingError } from "./quickReplayData.js";

const input = { exchange: "okx", marketType: "futures", symbol: "ETH-USDT-SWAP", interval: "1h" };
const bar = (time: number, close = 10) => ({ time, open: 10, high: 11, low: 9, close, volume: 1 });
const ready = (time: number): TransportKlineResponse => ({ data: [bar(time)], history_state: "ready", complete: true, retryable: false, all_rows_final: true });

test("cold repair retries the same range and publishes only the final snapshot", async () => {
  const calls: number[] = [];
  const responses: TransportKlineResponse[] = [
    { data: [], history_state: "pending", retryable: true },
    { data: [bar(7200, 99)], history_state: "pending", retryable: true },
    ready(7200),
  ];
  const result = await loadReplayBars(input, 0, 10800, undefined, {
    fetchRange: async (...args) => { calls.push(args[3]!); return responses.shift()!; },
    wait: async () => {},
  });
  assert.deepEqual(calls, [10800, 10800, 10800]);
  assert.deepEqual(result, { bars: [bar(7200)], truncated: false });
});

test("repair attempts do not consume backwards pagination budget", async () => {
  const ends: number[] = [];
  const responses: TransportKlineResponse[] = [
    { data: [], history_state: "pending" },
    { ...ready(7200), truncated: true, next_end_ms: 3600000 },
    ready(0),
  ];
  const result = await loadReplayBars(input, 0, 10800, undefined, {
    fetchRange: async (...args) => { ends.push(args[3]!); return responses.shift()!; },
    wait: async () => {},
  });
  assert.deepEqual(ends, [10800, 10800, 3600]);
  assert.deepEqual(result.bars.map((row) => row.time), [0, 7200]);
});

test("persistent repair is bounded and remains pending rather than empty or partially ready", async () => {
  let calls = 0;
  await assert.rejects(loadReplayBars(input, 0, 10800, undefined, {
    fetchRange: async () => { calls += 1; return { data: [bar(0)], history_state: "pending", retryable: true }; },
    wait: async () => {},
  }), ReplayHistoryPendingError);
  assert.equal(calls, 6);
});

test("terminal empty history does not retry", async () => {
  const result = await loadReplayBars(input, 0, 10800, undefined, {
    fetchRange: async () => ({ data: [], history_state: "exhausted", complete: false, retryable: false }),
    wait: async () => { assert.fail("terminal history must not retry"); },
  });
  assert.deepEqual(result.bars, []);
});

test("leaving replay cancels repair before another request or a late ready result", async () => {
  for (const pending of [true, false]) {
    const controller = new AbortController();
    let calls = 0;
    await assert.rejects(loadReplayBars(input, 0, 10800, controller.signal, {
      fetchRange: async () => {
        calls += 1;
        if (!pending) controller.abort();
        return pending ? { data: [], history_state: "pending" } : ready(0);
      },
      wait: async () => { controller.abort(); },
    }), { name: "AbortError" });
    assert.equal(calls, 1);
  }
});
