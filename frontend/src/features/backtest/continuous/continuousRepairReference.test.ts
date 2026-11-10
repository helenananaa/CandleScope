import assert from "node:assert/strict";
import test from "node:test";
import { acknowledgeContinuousRepairIntent, readContinuousRepairIntent, saveContinuousRepairIntent,
  type ContinuousRepairIntent } from "./continuousRepairReference.js";

function storage() {
  const data = new Map<string, string>();
  return { data, getItem(key: string) { return data.get(key) ?? null; }, setItem(key: string, value: string) { data.set(key, value); } };
}
function intent(id = "one", key = "repair/stable"): ContinuousRepairIntent {
  return { schema: 1, runId: id, requestKey: key, createdAtMs: 1, body: { confirmed: true, resume_after: false, plan_id: "a".repeat(64),
    expected: { id, generation: 1, revision: 2, checkpoint_revision: 2, sequence: 25, event_time_ms: 1499999, data_revision: "source" } } };
}
test("saved repair consent restores only its request, with no code or automatic execution", () => {
  const data = storage(); saveContinuousRepairIntent(data, intent());
  assert.deepEqual(readContinuousRepairIntent(data, "one"), intent());
  assert.equal(readContinuousRepairIntent(data, "other"), null);
  assert.equal([...data.data.values()][0]!.includes("source_text"), false);
  assert.throws(() => saveContinuousRepairIntent(data, intent("one", "another")), /Recover/);
  assert.deepEqual(readContinuousRepairIntent(data, "one"), intent());
  saveContinuousRepairIntent(data, { ...intent(), body: { ...intent().body, plan_id: "b".repeat(64) } });
  assert.equal(readContinuousRepairIntent(data, "one")!.requestKey, "repair/stable");
});
test("acknowledgement clears only the matching request and retains sibling records", () => {
  const data = storage(); saveContinuousRepairIntent(data, intent()); saveContinuousRepairIntent(data, intent("two", "repair/two"));
  acknowledgeContinuousRepairIntent(data, "one", "different"); assert.ok(readContinuousRepairIntent(data, "one"));
  acknowledgeContinuousRepairIntent(data, "one", "repair/stable"); assert.equal(readContinuousRepairIntent(data, "one"), null);
  assert.deepEqual(readContinuousRepairIntent(data, "two"), intent("two", "repair/two"));
});
test("capacity, corrupt data and failed storage writes never evict unresolved consent", () => {
  const data = storage();
  for (let index = 0; index < 16; index++) saveContinuousRepairIntent(data, intent(String(index)));
  const before = [...data.data.values()][0]!;
  assert.throws(() => saveContinuousRepairIntent(data, intent("overflow")), /retained/);
  assert.equal([...data.data.values()][0], before);
  const key = [...data.data.keys()][0]!; data.setItem(key, "invalid existing data");
  assert.throws(() => readContinuousRepairIntent(data, "one"));
  assert.throws(() => saveContinuousRepairIntent(data, intent()));
  assert.equal(data.getItem(key), "invalid existing data");
  const denied = { getItem: () => null, setItem: () => { throw new Error("quota"); } };
  assert.throws(() => saveContinuousRepairIntent(denied, intent()), /quota/);
});
test("incomplete identity or implicit consent cannot be persisted as an accepted intent", () => {
  const data = storage();
  for (const body of [{ ...intent().body, confirmed: false }, { ...intent().body, expected: { id: "one" } },
    { ...intent().body, source_text: "private code" }, { ...intent().body, plan_id: ["a".repeat(64)] }])
    assert.throws(() => saveContinuousRepairIntent(data, { ...intent(), body } as ContinuousRepairIntent), /retained/);
  assert.equal(data.data.size, 0);
});
