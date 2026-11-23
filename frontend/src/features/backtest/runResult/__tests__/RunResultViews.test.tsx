import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { t } from "../../../../i18n/index.js";
import { parseRunResult, type RunResult } from "../runResult.js";
import { RunResultSummary, RunResultTradeList } from "../RunResultViews.js";
import { runResultTradeFocus, runResultWinRate } from "../runResultViewModel.js";

function fixture(name: string): RunResult {
  const raw: unknown = JSON.parse(readFileSync(new URL(`../../../../../tests/fixtures/run-result/${name}.run-result.json`, import.meta.url), "utf8"));
  return parseRunResult(raw);
}

test("trade focus uses the bars a round trip spans, so every family reviews the same bars", () => {
  const host = fixture("host-bar-builtin").trades[0]!;
  const native = fixture("native-pine").trades[0]!;
  assert.deepEqual(runResultTradeFocus(host), { id: host.id, entryTimeMs: 660_000, exitTimeMs: 900_000, entryPrice: 107.0107, exitPrice: 99.99 });
  assert.deepEqual([runResultTradeFocus(native).entryTimeMs, runResultTradeFocus(native).exitTimeMs], [660_000, 900_000]);
});

test("win rate is wins over closed trades, and undefined without trades", () => {
  const host = fixture("host-bar-builtin");
  assert.equal(runResultWinRate(host), host.summary.winning_trades / host.summary.trade_count);
  assert.equal(runResultWinRate({ ...host, summary: { ...host.summary, trade_count: 0, winning_trades: 0 } }), null);
});

test("the summary shows the run's own numbers and whose account they are", () => {
  const host = renderToStaticMarkup(<RunResultSummary result={fixture("host-bar-builtin")} locale="en-US" />);
  const native = renderToStaticMarkup(<RunResultSummary result={fixture("native-pine")} locale="en-US" />);
  assert.match(host, /data-authority="HOST"/);
  assert.ok(host.includes(t("native.external.equity")) && !host.includes(t("native.equity") + "<"));
  assert.match(native, /data-authority="SCRIPT"/);
  assert.ok(native.includes(t("native.equity")));
  for (const html of [host, native]) {
    assert.ok(html.includes(t("chartTester.result.netPnl")) && html.includes(t("chartTester.result.winRate")));
    assert.ok(html.includes(t("replay.shell.position")), "both oracle runs end with an open long");
  }
});

test("the trade list renders one row per round trip with the family's own costs", () => {
  const render = (name: string) => renderToStaticMarkup(
    <RunResultTradeList result={fixture(name)} locale="en-US" onLocateTrade={() => undefined} />);
  const host = render("host-bar-builtin"), native = render("native-pine");
  assert.match(host, /data-trade-count="4"/);
  assert.match(native, /data-trade-count="4"/);
  assert.equal((host.match(/role="row"/g) ?? []).length, 4);
  assert.ok(host.includes(`${t("report.long")} 1`));
  assert.match(native, /<span title="—">—<\/span>/, "native runs report no per-trade fees");
});

test("a run without trades explains why, naming rejections when there were any", () => {
  const base = fixture("host-bar-builtin");
  const empty = { ...base, trades: [], summary: { ...base.summary, trade_count: 0, winning_trades: 0 } };
  const quiet = renderToStaticMarkup(<RunResultTradeList result={empty} locale="en-US" onLocateTrade={() => undefined} />);
  assert.ok(quiet.includes(t("chartTester.result.zeroTradesDetail")));
  const rejected = renderToStaticMarkup(<RunResultTradeList locale="en-US" onLocateTrade={() => undefined}
    result={{ ...empty, rejections: [{ time_ms: null, bar_time_ms: null, side: "BUY", reason: "SPOT_INSUFFICIENT_CASH", order_id: null, explanation: null }] }} />);
  assert.ok(rejected.includes(t("chartTester.result.rejectedNoTrades")));
});
