import assert from "node:assert/strict";
import test from "node:test";
import type { ContinuousRun } from "../backtest/continuous/continuousTypes.js";
import { FORWARD_OPTION_PREFIX, forwardAccounts, forwardRunFromOption } from "./forwardAccounts.js";

const identity = { generation: 1, revision: 1, checkpoint_revision: 1, sequence: 1, event_time_ms: 0, data_revision: "r1" };
function run(id: string, market: Record<string, unknown> | undefined, account_rules: string | null): ContinuousRun {
  return { ...identity, id, phase: "RUNNING", ...(market ? { market } : {}), account_rules };
}

test("forward runs are listed by market and tell their account rules", () => {
  const listed = forwardAccounts([
    run("run-practice", { exchange: "binance", market_type: "futures", symbol: "BTCUSDT", interval: "1m" }, "PRACTICE_V1"),
    run("run-backtest", { exchange: "binance", market_type: "spot", symbol: "ETHUSDT", interval: "1m" }, null),
  ]);
  assert.deepEqual(listed.map((entry) => [entry.label, entry.practice]), [["BTCUSDT · 1m", true], ["ETHUSDT · 1m", false]]);
  assert.equal(forwardRunFromOption(listed[0]!.option), "run-practice");
});

test("runs on one market are told apart, and a run without a market is named by its id", () => {
  const market = { symbol: "BTCUSDT", interval: "1m" };
  const listed = forwardAccounts([run("run-aaaaaaaa1", market, null), run("run-bbbbbbbb2", market, null), run("older-run", undefined, null)]);
  assert.deepEqual(listed.map((entry) => entry.label), ["BTCUSDT · 1m · aaaaaaa1", "BTCUSDT · 1m · bbbbbbb2", "older-run"]);
});

test("practice account ids are not forward runs", () => {
  assert.equal(forwardRunFromOption("practice-1"), null);
  assert.equal(forwardRunFromOption(FORWARD_OPTION_PREFIX), null);
});
