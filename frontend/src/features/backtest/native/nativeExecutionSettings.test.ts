import assert from "node:assert/strict";
import test from "node:test";
import { datasetIdentityChanged, defaultExecutionDraft, executionSettingsChanged, restoreExecutionDraft, sameExecutionData } from "./nativeExecutionSettings.js";

test("an immutable report belongs to both its dataset and data revision", () => {
  const config = Object.freeze({ dataset_id: "LTC-six-bars", data_epoch: "original-epoch" });
  const original = { datasetId: config.dataset_id, dataEpoch: config.data_epoch };
  assert.equal(datasetIdentityChanged(config, original), false);
  assert.equal(datasetIdentityChanged(config, { ...original, dataEpoch: "changed-last-bar" }), true);
  assert.equal(datasetIdentityChanged(config, { ...original, datasetId: "another-import" }), true);
  assert.equal(datasetIdentityChanged({}, original), true);
  assert.equal(datasetIdentityChanged(undefined, original), true);
  assert.equal(datasetIdentityChanged(config, undefined), false);
  assert.equal(datasetIdentityChanged(config, original), false); // returning to the original revision restores relevance.
});

test("host execution draft round-trips every financial setting and upload requirement", () => {
  const draft = { hostSettings: { initial_balance: 20000, slippage_bps: 3, taker_fee_bps: 2, price_tick: .005 },
    fidelity: "TRADE_TAPE", fillRecalculation: true, uploaded: true };
  assert.deepEqual(restoreExecutionDraft(JSON.stringify(draft)), draft);
  assert.deepEqual(restoreExecutionDraft("broken"), defaultExecutionDraft());
  assert.equal(restoreExecutionDraft('{"hostSettings":{"initial_balance":0}}').hostSettings.initial_balance, 0);
  assert.equal(restoreExecutionDraft('{"fidelity":"FAKE"}').fidelity, "BAR_APPROX");
});

test("each changed execution setting invalidates the old host report", () => {
  const current = { ...defaultExecutionDraft(), fidelity: "TRADE_TAPE", fillRecalculation: true };
  const config = { host_settings: { ...current.hostSettings }, execution_fidelity: current.fidelity, fill_recalculation: true };
  assert.equal(executionSettingsChanged(config, current, true), false);
  for (const field of ["initial_balance", "slippage_bps", "taker_fee_bps", "price_tick"] as const) {
    assert.equal(executionSettingsChanged(config, { ...current,
      hostSettings: { ...current.hostSettings, [field]: current.hostSettings[field] + 1 } }, true), true, field);
  }
  assert.equal(executionSettingsChanged(config, { ...current, fidelity: "BAR_APPROX" }, true), true);
  assert.equal(executionSettingsChanged(config, { ...current, fillRecalculation: false }, true), true);
  assert.equal(executionSettingsChanged(config, current, false), true);
  assert.equal(executionSettingsChanged({ ...config, execution_fidelity: "BAR_APPROX" },
    { ...current, fidelity: "BAR_APPROX" }, false), false); // BAR ignores files and fill callbacks.
});

test("uploaded tapes compare by content and event order, without object-key ordering artifacts", () => {
  const left = { symbol: "LTCUSDT", events: [{ time_ms: 1, payload: { price: "63.45", qty: "1" } }] };
  const reordered = { events: [{ payload: { qty: "1", price: "63.45" }, time_ms: 1 }], symbol: "LTCUSDT" };
  assert.equal(sameExecutionData(left, reordered), true);
  assert.equal(sameExecutionData(left, { ...reordered, provenance: {} }), true);
  assert.equal(sameExecutionData(left, { ...left, events: [{ time_ms: 2, payload: left.events[0]!.payload }] }), false);
  assert.equal(sameExecutionData(left, null), false);
  assert.equal(sameExecutionData(undefined, null), true);
  assert.equal(sameExecutionData([1, 2], [2, 1]), false);
  const nested = () => Array.from({ length: 1000 }).reduce<unknown>((value) => ({ value }), 1);
  assert.equal(sameExecutionData(nested(), nested()), false);
});
