import assert from "node:assert/strict";
import test from "node:test";
import { createActiveIndicatorPersistence } from "../../indicators/activeIndicatorStore.js";
import type { IndicatorDefinition } from "../../indicators/indicatorTypes.js";
import type { LocalDatasetManifest } from "../../local-data/localDataTypes.js";
import { ResearchIndicatorScopeStore } from "../researchIndicatorScope.js";

function memory() {
  const values = new Map<string, string>();
  return { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value); } };
}
function data(id: string, epoch = "1"): LocalDatasetManifest {
  return { schema_version: 1, dataset_id: id, data_epoch: epoch, name: id, source: "local_dataset",
    symbol: id, interval: "1m", volume_available: true, timezone: "UTC", timestamp_semantics: "bar_open",
    rows: 10, first_open_ms: 0, last_open_ms: 540000, all_rows_final: true, excluded_range_count: 0,
    sqlite_sha256: id, imported_at: "2026-11-08" };
}
const ma: IndicatorDefinition = { id: "study", is_builtin: true, engineName: "MA", params: { length: 5 }, lines: [] };

test("a shared indicator preserves dataset revisions, propagates edits and leaves unrelated local indicators alone", async () => {
  const a = data("a"), b = data("b"), newB = data("b", "2");
  const storage = memory();
  const one = createActiveIndicatorPersistence("a", storage), two = createActiveIndicatorPersistence("b", storage);
  one.save([ma]);
  two.save([{ ...ma, id: "independent", params: { length: 11 } }]);
  const owner = new ResearchIndicatorScopeStore(storage);
  await owner.apply(ma, a, [a, b], one);
  const project = (dataset: LocalDatasetManifest, local: typeof one) => owner.chartPersistence(dataset, owner.snapshot().scopes, local);
  assert.deepEqual(project(a, one).load().map(row => row.id), ["study"]);
  assert.deepEqual(project(b, two).load().map(row => row.id), ["independent", "study"]);
  assert.deepEqual(project(newB, createActiveIndicatorPersistence("b2", storage)).load(), []);
  assert.deepEqual(one.load(), []);

  project(b, two).save(project(b, two).load().map(row => row.id === ma.id ? { ...row, params: { length: 9 } } : row));
  assert.equal(project(a, one).load()[0]?.params?.length, 9);
  assert.equal(two.load()[0]?.params?.length, 11);
  await Promise.resolve();
  const restored = new ResearchIndicatorScopeStore(storage);
  assert.deepEqual(restored.chartPersistence(a, restored.snapshot().scopes, one).load(), project(a, one).load());

  project(b, two).save(two.load());
  assert.equal(project(b, two).load().some(row => row.id === ma.id), false);
  assert.equal(project(a, one).load()[0]?.params?.length, 9);
});

test("a failed shared write keeps the original local indicator and rejects further mutations", async () => {
  const storage = memory(), a = data("a"), b = data("b");
  const local = createActiveIndicatorPersistence("a", storage);
  local.save([ma]);
  const owner = new ResearchIndicatorScopeStore({ getItem: storage.getItem, setItem: () => { throw new Error("disk full"); } });
  await assert.rejects(owner.apply(ma, a, [a, b], local), /disk full/);
  assert.deepEqual(owner.snapshot(), { scopes: [], storageError: true });
  assert.equal(local.load()[0]?.id, ma.id);
});
