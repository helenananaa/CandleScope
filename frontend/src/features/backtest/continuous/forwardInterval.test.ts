import assert from "node:assert/strict";
import test from "node:test";
import { forwardBarOpenMs, forwardIntervalMs } from "./forwardInterval.js";

const MONDAY = Date.UTC(2026, 10, 23);

test("forward runs follow fixed-length intervals of whole minutes (B-333)", () => {
  assert.deepEqual(["1m", "5m", "15m", "1h", "4h", "1d", "1w"].map(forwardIntervalMs),
    [60_000, 300_000, 900_000, 3_600_000, 14_400_000, 86_400_000, 604_800_000]);
  for (const refused of ["1M", "30s", "", "x"]) assert.equal(forwardIntervalMs(refused), null, refused);
});

test("a history start is the open of its bar on the run's grid", () => {
  assert.equal(forwardBarOpenMs("5m", MONDAY + 7 * 60_000), MONDAY + 5 * 60_000);
  assert.equal(forwardBarOpenMs("1h", MONDAY + 59 * 60_000), MONDAY);
  assert.equal(forwardBarOpenMs("1w", MONDAY + 3 * 86_400_000), MONDAY);
  assert.equal(forwardBarOpenMs("1M", MONDAY), null);
});
