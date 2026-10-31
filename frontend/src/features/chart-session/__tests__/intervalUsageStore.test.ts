import assert from "node:assert/strict";
import test from "node:test";
import { rankWarmIntervals, sanitizeIntervalUsage } from "../intervalUsageStore.js";

test("usage input is canonical, deduplicated, bounded and rejects corrupt values", () => {
  const input = sanitizeIntervalUsage([{ interval: "60m", count: 2, lastUsed: 10 }, { interval: "1h", count: 3, lastUsed: 20 },
    { interval: "5m", count: -1, lastUsed: 10 }, { interval: "15m", count: Infinity, lastUsed: 10 }, null]);
  assert.deepEqual(input, [{ interval: "1h", count: 3, lastUsed: 20 }]);
  assert.equal(sanitizeIntervalUsage(Array.from({ length: 100 }, (_, index) => ({ interval: `${index + 1}m`, count: 1, lastUsed: index }))).length, 64);
});

test("warming ranks a bounded set of available habits and pins without selecting the active or unsupported interval", () => {
  assert.deepEqual(rankWarmIntervals({ available: ["1m", "5m", "15m", "1h", "4h", "1d"], active: "60m",
    pinned: ["1m", "5m", "1h"], now: 100, usage: [
      { interval: "15m", count: 20, lastUsed: 100 }, { interval: "1w", count: 1_000, lastUsed: 100 },
    ] }), ["15m", "1m", "5m"]);
  assert.deepEqual(rankWarmIntervals({ available: ["1s", "5s"], active: "1m", pinned: ["1m"], usage: [] }), []);
});
