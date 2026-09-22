import assert from "node:assert/strict";
import test from "node:test";
import { restorePreparationContexts, restorePreparationDate } from "./nativePreparationInputs.js";

test("restore explicit history declarations and automatic defaults without accepting malformed drafts", () => {
  const automatic = { exchange: "binance", market_type: "futures", symbol: "ETHUSDT", interval: "1h", binding_symbol: "" };
  const explicit = { ...automatic, warmup_bars: 20 };
  assert.deepEqual(restorePreparationContexts(JSON.parse(JSON.stringify([automatic, explicit]))), [automatic, explicit]);
  assert.deepEqual(restorePreparationContexts([null, {}, { ...explicit, warmup_bars: "20" }, { ...explicit, warmup_bars: -1 }]), []);
  assert.deepEqual(restorePreparationContexts(undefined), []);
});

test("restores UTC date drafts including unfinished edits without normalizing invalid calendar dates", () => {
  assert.equal(restorePreparationDate("2024-02-29", "2026-09-22"), "2024-02-29");
  assert.equal(restorePreparationDate("", "2026-09-22"), "");
  assert.equal(restorePreparationDate("2023-02-29", "2026-09-22"), "2026-09-22");
  assert.equal(restorePreparationDate(undefined, "2026-09-22"), "2026-09-22");
});
