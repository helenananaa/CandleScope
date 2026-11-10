import assert from "node:assert/strict";
import test from "node:test";
import { activateContinuousReference, continuousArchiveScope, continuousReferenceKey, listContinuousReferences, readContinuousReference, saveContinuousReference, type ContinuousRunReference } from "./continuousRunReference.js";
import { loadChartStrategyPanelPreferences, saveChartStrategyPanelPreferences } from "../chart-tester/chartStrategyPanelPreferences.js";
function storage(): Storage {
  const values = new Map<string, string>();
  return { get length() { return values.size; }, key(index) { return [...values.keys()][index] ?? null; },
    clear() { values.clear(); }, getItem(key) { return values.get(key) ?? null; }, removeItem(key) { values.delete(key); }, setItem(key, value) { values.set(key, value); } };
}
const reference: ContinuousRunReference = { schema: 1, requestKey: "chart/stable", runId: null, inputRevision: "123", createdAtMs: 1,
  settings: { from: "2026-11-01T00:00", balance: "1000", percent: "10", fee: "4", slippage: "1", output: "SIGNAL" } };
test("uncertain creation key and settings survive a new reader; account references remain scope-specific", () => {
  const saved = storage(); saveContinuousReference(saved, "cell/A/history", reference);
  assert.deepEqual(readContinuousReference(saved, "cell/A/history"), reference);
  saveContinuousReference(saved, "cell/A/history", { ...reference, runId: "account" });
  assert.equal(readContinuousReference(saved, "cell/A/history")!.requestKey, "chart/stable");
  assert.equal(readContinuousReference(saved, "cell/A/live"), null); assert.equal(readContinuousReference(saved, "cell/B/history"), null);
});
test("malformed or over-capacity references preserve existing local records", () => {
  const saved = storage(); saved.setItem(continuousReferenceKey("bad"), "{invalid");
  assert.throws(() => readContinuousReference(saved, "bad")); assert.equal(saved.getItem(continuousReferenceKey("bad")), "{invalid");
  for (let index = 0; index < 63; index += 1) saveContinuousReference(saved, String(index), reference);
  assert.throws(() => saveContinuousReference(saved, "overflow", reference), /CAPACITY/);
  saveContinuousReference(saved, "0", { ...reference, runId: "restored" });
  assert.equal(saved.length, 64); assert.equal(readContinuousReference(saved, "0")!.runId, "restored");
});
test("saved run mode survives preference reload and old preferences keep historical default", () => {
  const saved = storage(); saveChartStrategyPanelPreferences("cell", { height: 300, activeTab: "script", runMode: "LIVE_ONLY" }, saved);
  assert.equal(loadChartStrategyPanelPreferences("cell", saved).runMode, "LIVE_ONLY");
  assert.equal(loadChartStrategyPanelPreferences("old", saved).runMode, undefined);
});
test("switching runs retains earlier accounts and uncertain requests within the same series scope", () => {
  const saved = storage(); activateContinuousReference(saved, "cell", reference);
  const next = { ...reference, createdAtMs: 2, requestKey: "chart/new", runId: "next-account" };
  activateContinuousReference(saved, "cell", next);
  assert.deepEqual(listContinuousReferences(saved, "cell").map((value) => value.requestKey), ["chart/new", "chart/stable"]);
  assert.deepEqual(listContinuousReferences(saved, "other-cell"), []);
  saveContinuousReference(saved, continuousArchiveScope("cell", next.requestKey), next);
  assert.equal(listContinuousReferences(saved, "cell").length, 2, "current and archive references are deduplicated");
});
