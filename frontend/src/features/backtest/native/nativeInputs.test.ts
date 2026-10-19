import assert from "node:assert/strict";
import test from "node:test";
import { automaticHostExecution, emptyAdvancedInputs, executionInputs, freezeAdvancedInputs, freezePineChartContexts, restoreAdvancedInputs, type InputDataset } from "./nativeInputs.js";
import { nativeApi } from "./nativeBacktestApi.js";

const dataset: InputDataset = { dataset_id: "data", data_epoch: "epoch1", name: "ETH", symbol: "ETHUSDT",
  interval: "1m", first_open_ms: 0, last_close_ms: 599999 };
const main = { start_time_ms: 60000, end_time_ms: 299999, exchange: "binance", market_type: "spot" };

test("chart and native requests freeze the selected venue and market instead of the primary chart", async () => {
  const calls: unknown[] = [];
  const other = { ...dataset, exchange: "okx", market_type: "futures" };
  const choices = [{ dataset: other, symbol: "OKX:ETHUSDT", marketType: "futures" }];
  const contexts = await freezePineChartContexts(choices, main, mockApi([other], calls));
  assert.equal(contexts[0]?.exchange, "okx");
  assert.equal(contexts[0]?.market_type, "futures");
  assert.equal(contexts[0]?.start_time_ms, 0);
  const native = await freezeAdvancedInputs({ ...emptyAdvancedInputs(), contexts: choices }, "pine", main, mockApi([other], []));
  assert.deepEqual(native.contexts, contexts);
  await assert.rejects(freezePineChartContexts([{ ...choices[0]!, marketType: "spot" }], main, mockApi([other], [])), /provenance/);
  await assert.rejects(freezePineChartContexts([{ ...choices[0]!, symbol: "BINANCE:ETHUSDT" }], main, mockApi([other], [])), /provenance/);
});

test("advanced source dependencies and partial JSON edits survive draft restoration without trusting stale datasets", async () => {
  const input = { contexts: [{ dataset, symbol: "BINANCE:ETHUSDT" }], magnifier: dataset,
    libraries: "{", priceTickSize: ".1", currency: "USDT", currencyRates: "{" };
  assert.deepEqual(restoreAdvancedInputs(JSON.parse(JSON.stringify(input))), input);
  assert.deepEqual(restoreAdvancedInputs({ contexts: [{ dataset: {}, symbol: "x" }], libraries: 1 }), emptyAdvancedInputs());
  assert.throws(() => restoreAdvancedInputs({ contexts: [{ dataset: {}, symbol: "x" }] }, true), /malformed/);
  assert.throws(() => restoreAdvancedInputs({ contexts: Array(17).fill({ dataset, symbol: "x" }) }, true), /at most 16/);
  const valid = restoreAdvancedInputs({ ...input, libraries: "{}", currencyRates: "" });
  await assert.rejects(freezeAdvancedInputs(valid, "pine", main, mockApi([], [])), /changed/);
});

test("requested instrument metadata is frozen and survives draft restore", async () => {
  const selection = { ...emptyAdvancedInputs(), contexts: [{ dataset, symbol: "OKX:ETHUSDT", marketType: "spot",
    priceTickSize: ".25", currency: "USDT", quantityPrecision: "3" }] };
  assert.deepEqual(restoreAdvancedInputs(selection), selection);
  const contexts = await freezePineChartContexts(selection.contexts, main, mockApi([dataset], []));
  assert.deepEqual(contexts[0]?.metadata, { priceTickSize: ".25", currency: "USDT", quantityPrecision: 3 });
  await assert.rejects(freezePineChartContexts([{ ...selection.contexts[0]!, priceTickSize: "" }], main, mockApi([dataset], [])), /actual price tick/);
});
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

test("automatic execution keeps uploaded tapes authoritative and ignores stale uploads in BAR mode", () => {
  const settings = { initial_balance: 3210, slippage_bps: 2 };
  assert.equal(automaticHostExecution("NATIVE", settings, "TRADE_TAPE", true, {}), null);
  assert.deepEqual(automaticHostExecution("CANDLESCOPE", settings, "BAR_APPROX", true, {}), {
    execution_fidelity: "BAR_APPROX", host_settings: settings, fill_recalculation: false,
  });
  assert.deepEqual(automaticHostExecution("CANDLESCOPE", settings, "TRADE_TAPE", true, null), {
    execution_fidelity: "TRADE_TAPE", host_settings: settings, fill_recalculation: true,
  });
  assert.equal(automaticHostExecution("CANDLESCOPE", settings, "TRADE_TAPE", true, {}), undefined);
  assert.equal(automaticHostExecution("CANDLESCOPE", settings, "BOOK_DEPTH", false, null), undefined);
});
