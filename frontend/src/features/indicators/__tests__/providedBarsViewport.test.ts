import assert from "node:assert/strict";
import test from "node:test";
import { providedBarsViewport } from "../providedBarsViewport.js";
import type { KlineBar } from "../../market-data/marketDataTypes.js";
import { structuralMock } from "../../../test/testHelpers.js";

const rows = Array.from({ length: 10_000 }, (_, i) => structuralMock<KlineBar>({ time: 1_800_000_000 + i * 60 }));

test("display bootstrap requests a bounded recent viewport instead of every loaded bar", () => {
  const plan = providedBarsViewport(rows, null);
  assert.equal(plan.bars.at(-1), rows.at(-1));
  assert.ok(plan.bars.length < 1000);
});

test("pan and zoom prioritize the actual viewport, with live padding and no hidden suffix", () => {
  const range = { time: { from: rows[3000]!.time, to: rows[3200]!.time } };
  const plan = providedBarsViewport(rows, range);
  assert.equal(plan.bars.at(-1), rows[3200]);
  assert.ok(plan.bars.includes(rows[3000]!));
  assert.ok(plan.bars.length < 500);
  assert.equal(providedBarsViewport(rows, range).key, plan.key);
  const zoom = providedBarsViewport(rows, { logical: { from: 3050, to: 3100 } });
  assert.equal(zoom.bars.at(-1), rows[3100]);
  assert.ok(zoom.bars.length < plan.bars.length);
});
