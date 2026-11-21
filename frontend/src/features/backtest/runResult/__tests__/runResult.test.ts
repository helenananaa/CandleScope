import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { parseRunResult, RUN_RESULT_SCHEMA, RunResultContractError } from "../runResult.js";

// Written by the backend projection of the ADR-BACKTEST-015 P0 oracle runs and kept equal to it
// by backend/tests/test_run_result*.py, so these tests exercise the real wire contract.
type WireRow = Record<string, unknown>;
interface Wire extends WireRow { fills: WireRow[] }

function fixture(name: string): Wire {
  return JSON.parse(readFileSync(new URL(`../../../../../tests/fixtures/run-result/${name}.run-result.json`, import.meta.url), "utf8")) as Wire;
}

function firstFill(value: Wire): WireRow {
  const fill = value.fills[0];
  assert.ok(fill, "the fixture has fills");
  return fill;
}

test("the host projection of the oracle run parses with every fill anchored to a bar", () => {
  const result = parseRunResult(fixture("host-bar-builtin"));
  assert.equal(result.schema, RUN_RESULT_SCHEMA);
  assert.equal(result.authority, "HOST");
  assert.equal(result.source, "host-kernel");
  assert.equal(result.fills.length, result.summary.fill_count);
  assert.equal(result.trades.length, result.summary.trade_count);
  assert.ok(result.fills.every((fill) => fill.bar_time_ms !== null && fill.bar_time_ms % 60_000 === 0));
  assert.deepEqual(result.fills[0], {
    time_ms: 719_999, bar_time_ms: 660_000, side: "BUY", qty: "1", price: "107.0107", fee: "0.03210321", order_id: "ord-1", tag: null,
  });
  assert.equal(result.open_position?.side, "LONG");
  assert.deepEqual(result.plots, []);
});

test("the native projection keeps script authority, plots and the same fill bars as the host run", () => {
  const native = parseRunResult(fixture("native-pine"));
  const host = parseRunResult(fixture("host-bar-builtin"));
  assert.equal(native.authority, "SCRIPT");
  assert.equal(native.plots.length, 2);
  assert.ok(native.plots.every((plot) => plot.points.length > 0 && plot.points[0]![1] === null));
  // The two engines stamp fills differently but fill on the same bars once projected.
  assert.deepEqual(native.fills.map((fill) => [fill.bar_time_ms, fill.side]), host.fills.map((fill) => [fill.bar_time_ms, fill.side]));
  assert.ok(native.fills.every((fill) => fill.fee === null));
});

const MALFORMED: ReadonlyArray<readonly [string, (value: Wire) => void]> = [
  ["a different schema", (value) => { value.schema = "candlescope.run-result/2"; }],
  ["an unknown authority", (value) => { value.authority = "PLUGIN"; }],
  ["a float price", (value) => { firstFill(value).price = 107.0107; }],
  ["a non-canonical decimal", (value) => { firstFill(value).qty = "1.0"; }],
  ["fractional milliseconds", (value) => { firstFill(value).time_ms = 719_999.5; }],
  ["an unknown fill side", (value) => { firstFill(value).side = "SHORT"; }],
  ["a missing trade list", (value) => { delete value.trades; }],
  ["a non-finite plot value", (value) => { value.plots = [{ id: "7", title: null, kind: "line", pane: "main", points: [[0, "x"]] }]; }],
];

for (const [label, mutate] of MALFORMED) {
  test(`parseRunResult rejects ${label}`, () => {
    const value = fixture("host-bar-builtin");
    mutate(value);
    assert.throws(() => parseRunResult(value), RunResultContractError);
  });
}
