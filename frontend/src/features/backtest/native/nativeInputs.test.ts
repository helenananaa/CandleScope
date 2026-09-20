import assert from "node:assert/strict";
import test from "node:test";
import { emptyAdvancedInputs, executionInputs, freezeAdvancedInputs, type InputDataset } from "./nativeInputs.js";
import { nativeApi } from "./nativeBacktestApi.js";

const dataset: InputDataset = { dataset_id: "data", data_epoch: "epoch1", name: "ETH", symbol: "ETHUSDT",
  interval: "1m", first_open_ms: 0, last_close_ms: 599999 };
const main = { start_time_ms: 60000, end_time_ms: 299999, exchange: "binance", market_type: "spot" };
function mockApi(datasets: InputDataset[], calls: unknown[]) {
  return (async (path: string, body?: unknown) => {
    calls.push({ path, body });
    return path === "/datasets" ? { datasets } : { snapshot_hash: "fixed-hash" };
  }) as typeof nativeApi;
}

test("freeze requested data and magnifier with distinct authoritative ranges", async () => {
  const calls: unknown[] = [];
  const result = await freezeAdvancedInputs({ contexts: [{ dataset, symbol: "BINANCE:ETHUSDT" }],
    magnifier: dataset, libraries: '{"author/library/1":"export f() => 1"}' }, "pine", main, mockApi([dataset], calls));
  assert.equal(result.contexts[0]?.start_time_ms, 0);
  assert.equal(result.contexts[0]?.end_time_ms, 599999);
  assert.equal(result.contexts[0]?.timeframe, "1");
  assert.equal(result.contexts[0]?.snapshot_hash, "fixed-hash");
  assert.equal(result.magnifier?.start_time_ms, 60000);
  assert.equal(result.magnifier?.end_time_ms, 299999);
  assert.equal(calls.length, 3);
});

test("stale selected revision and duplicate request keys fail before snapshotting", async () => {
  const calls: unknown[] = [];
  const choice = { dataset, symbol: "BINANCE:ETHUSDT" };
  await assert.rejects(freezeAdvancedInputs({ ...emptyAdvancedInputs(), contexts: [choice] }, "pyne", main,
    mockApi([{ ...dataset, data_epoch: "changed" }], calls)), /DATA_SNAPSHOT_MISMATCH/);
  assert.equal(calls.length, 1);
  await assert.rejects(freezeAdvancedInputs({ ...emptyAdvancedInputs(), contexts: [choice, choice] }, "pine", main,
    mockApi([dataset], calls)), /duplicate/);
  assert.equal(calls.length, 1);
});

test("unsupported libraries and malformed library JSON never reach the run API", async () => {
  for (const libraries of ['[]', '{"library":42}', 'broken']) {
    await assert.rejects(freezeAdvancedInputs({ ...emptyAdvancedInputs(), libraries }, "pine", main));
  }
  await assert.rejects(freezeAdvancedInputs({ ...emptyAdvancedInputs(), libraries: '{"lib":"source"}' }, "pyne", main), /require Pine/);
});

test("shared execution payload preserves fill callback for both chart entry points", () => {
  const settings = { initial_balance: 10000, slippage_bps: 0, taker_fee_bps: 0 };
  const tape = { events: [1] };
  assert.deepEqual(executionInputs("CANDLESCOPE", settings, "TRADE_TAPE", true, tape), {
    host_settings: settings, execution_fidelity: "TRADE_TAPE", fill_recalculation: true, execution_data: tape,
  });
  assert.equal(executionInputs("CANDLESCOPE", settings, "BAR_APPROX", true, tape).fill_recalculation, false);
  assert.deepEqual(executionInputs("NATIVE", settings, "TRADE_TAPE", true, tape), {});
});
