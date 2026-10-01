import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { NativeStrategyReport } from "../NativeStrategyReport.js";
import type { NativeRun } from "../nativeBacktestApi.js";

function report(values: number[], tradeCount = 0, view: "overview" | "trades" = "overview") {
  const run: NativeRun = {
    execution_mode: "CANDLESCOPE", run_id: "layout-test", state: "COMPLETED", created_at_ms: 0,
    runtime_identity: { engine: { package: "test", version: "1", code_sha256: "test" } },
    result: { account_authority: "test", fill_model: "test", report_hash: "test", trades: Array.from({ length: tradeCount }, (_, index) => ({ id: `trade-${index}`, entryTime: 1700000000 + index * 3600, profit: index - 20 })), orders: [],
      bars: [], graphics: [], raw_output: {}, diagnostics: [],
      equity: values.map((value, time) => ({ time, value })) },
  };
  return renderToStaticMarkup(<NativeStrategyReport run={run} view={view} />);
}
test("report drawdown uses successive peaks, not the first or last equity", () => {
  assert.match(report([100, 200, 150, 190]), /25%/);
  assert.doesNotMatch(report([100, 200, 150, 190]), /NaN|Infinity/);
});
test("missing equity samples render unavailable instead of a false zero drawdown", () => {
  assert.match(report([]), /<strong>—<\/strong>/);
  assert.match(report([100]), /<strong>—<\/strong>/);
});

test("long trade reports bound rendered rows and jump input to the actual result", () => {
  const html = report([100, 110], 121, "trades");
  assert.equal((html.match(/data-selected="false"/g) ?? []).length, 50);
  assert.match(html, /<input(?=[^>]*name="trade")(?=[^>]*min="1")(?=[^>]*max="121")[^>]*>/);
  assert.match(html, /trade-49/);
  assert.doesNotMatch(html, /trade-50/);
  assert.match(html, /class="native-trade-pages"/);
});
test("empty trade results disable the jump form and both trade navigation actions", () => {
  const html = report([], 0, "trades");
  assert.match(html, /<input(?=[^>]*name="trade")(?=[^>]*disabled="")[^>]*>/);
  assert.match(html, /type="submit" disabled=""/);
  assert.doesNotMatch(html, /data-selected="false"/);
});
