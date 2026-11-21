import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { RunResultContractError } from "../../backtest/runResult/runResult.js";
import { StrategyDataManager, type StrategyDataApi } from "../manager/strategyDataManager.js";

const HOST: unknown = JSON.parse(readFileSync(new URL("../../../../tests/fixtures/run-result/host-bar-builtin.run-result.json", import.meta.url), "utf8"));
const NATIVE: unknown = JSON.parse(readFileSync(new URL("../../../../tests/fixtures/run-result/native-pine.run-result.json", import.meta.url), "utf8"));

function api(overrides: Partial<StrategyDataApi> = {}): StrategyDataApi {
  return overrides as StrategyDataApi;
}

test("run results are read once per family and run, then served from the bounded cache", async () => {
  const calls: string[] = [];
  const manager = new StrategyDataManager(api({
    async getRunResult(runId) { calls.push(`host:${runId}`); return structuredClone(HOST); },
    async getPineRunResult(mode, runId) { calls.push(`${mode}:${runId}`); return structuredClone(NATIVE); },
  }));
  const host = await manager.loadRunResult("host", "r1");
  assert.equal(await manager.loadRunResult("host", "r1"), host);
  assert.equal((await manager.loadRunResult("native", "r1")).authority, "SCRIPT");
  assert.deepEqual(calls, ["host:r1", "native:r1"]);
  for (let index = 2; index <= 9; index += 1) await manager.loadRunResult("host", `r${index}`);
  assert.equal(manager.diagnostics().runResults, 8);
  await manager.loadRunResult("native", "r1");
  assert.equal(calls.filter((call) => call === "native:r1").length, 2, "the oldest entry was evicted");
  manager.dispose();
  assert.equal(manager.diagnostics().runResults, 0);
});

test("a result served under the wrong family is rejected instead of being drawn", async () => {
  const manager = new StrategyDataManager(api({ async getPineRunResult() { return structuredClone(HOST); } }));
  await assert.rejects(manager.loadRunResult("native", "r1"), RunResultContractError);
  await assert.rejects(manager.loadRunResult("external", "r1"), RunResultContractError);
  assert.equal(manager.diagnostics().runResults, 0, "rejected results are not cached");
  manager.dispose();
});

test("missing endpoints and aborted reads fail without caching", async () => {
  const manager = new StrategyDataManager(api({
    async getRunResult(_runId, signal) {
      await new Promise((resolve) => setTimeout(resolve, 5));
      signal?.throwIfAborted();
      return structuredClone(HOST);
    },
  }));
  await assert.rejects(manager.loadRunResult("native", "r1"), /unavailable/i);
  const controller = new AbortController();
  const pending = manager.loadRunResult("host", "r1", controller.signal);
  controller.abort(new Error("consumer left"));
  await assert.rejects(pending);
  assert.equal(manager.diagnostics().runResults, 0);
  assert.equal(manager.diagnostics().operations, 0);
  manager.dispose();
});
