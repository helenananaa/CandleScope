import assert from "node:assert/strict";
import test from "node:test";
import { createConfiguredProjectionStore } from "../configuredProjectionStore.js";

const prices = (scale: number) => Array.from({ length: 40 }, (_, index) => {
  const close = Number(((63.4 + Math.sin(index / 2) * 0.2) * scale).toFixed(8));
  return { time: 1_710_000_000 + index * 60, open: close, close,
    high: Number((close + 0.03 * scale).toFixed(8)),
    low: Number((close - 0.03 * scale).toFixed(8)), volume: 1 };
});

for (const type of ["renko", "point-and-figure", "kagi"] as const) {
  for (const scale of [1, 0.001]) {
    test(`${type} async cold history matches warm history at price scale ${scale}`, () => {
      const rows = prices(scale);
      const warm = createConfiguredProjectionStore(type, rows, { mode: "atr", atrLength: 14 });
      warm.reset(rows);
      const cold = createConfiguredProjectionStore(type, [], { mode: "atr", atrLength: 14 });
      cold.reset([]);
      const fallbackKey = cold.configurationKey;
      cold.applySourceDelta({ type: "replace" }, rows.slice(-2));
      cold.applySourceDelta({ type: "prepend", addedLeft: rows.length - 2 }, rows);
      assert.notEqual(cold.configurationKey, fallbackKey);
      assert.equal(cold.configurationKey, warm.configurationKey);
      assert.deepEqual(cold.displaySnapshot(), warm.displaySnapshot());
      assert.ok(cold.displaySnapshot().length > 1);
      cold.applySourceDelta({ type: "clear" }, []);
      const otherMarket = prices(scale / 10);
      cold.applySourceDelta({ type: "replace" }, otherMarket);
      const otherWarm = createConfiguredProjectionStore(type, otherMarket);
      otherWarm.reset(otherMarket);
      assert.deepEqual(cold.displaySnapshot(), otherWarm.displaySnapshot());
    });
  }
}

test("fixed price grids keep the requested box while discovering source precision", () => {
  const rows = prices(0.001);
  const cold = createConfiguredProjectionStore("point-and-figure", [], { mode: "traditional", boxSize: 0.00005 });
  cold.reset([]);
  cold.applySourceDelta({ type: "replace" }, rows);
  const warm = createConfiguredProjectionStore("point-and-figure", rows, { mode: "traditional", boxSize: 0.00005 });
  warm.reset(rows);
  assert.deepEqual(cold.displaySnapshot(), warm.displaySnapshot());
});

for (const type of ["renko", "point-and-figure", "kagi"] as const) {
  test(`${type} advancing, reloading and correcting the same revealed prefix agree`, () => {
    const rows = prices(1);
    const settings = { mode: "atr" as const, atrLength: 14 };
    const live = createConfiguredProjectionStore(type, rows, settings);
    live.reset(rows);
    const last = rows.at(-1)!;
    const jump = { ...last, time: last.time + 60, high: 75, low: 62, close: 74 };
    const atJump = [...rows, jump];
    live.applySourceDelta({ type: "append", addedRight: 1 }, atJump);
    const restored = createConfiguredProjectionStore(type, atJump, settings);
    restored.reset(atJump);
    assert.equal(live.configurationKey, restored.configurationKey);
    assert.deepEqual(live.displaySnapshot(), restored.displaySnapshot());

    const corrected = [...rows, { ...jump, high: 63.7, low: 63.2, close: 63.5 }];
    live.applySourceDelta({ type: "replace" }, corrected);
    const correctedReload = createConfiguredProjectionStore(type, corrected, settings);
    correctedReload.reset(corrected);
    assert.equal(live.configurationKey, correctedReload.configurationKey);
    assert.deepEqual(live.displaySnapshot(), correctedReload.displaySnapshot());
  });
}
