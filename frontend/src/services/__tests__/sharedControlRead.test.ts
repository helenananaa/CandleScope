import assert from "node:assert/strict";
import test from "node:test";

import {
  invalidateSharedControlRead,
  resetSharedControlReadsForTests,
  sharedControlRead,
  sharedControlReadCountForTests,
} from "../sharedControlRead.js";

test("shared control reads coalesce inflight work and reuse a bounded TTL value", async () => {
  resetSharedControlReadsForTests();
  let calls = 0;
  const load = async () => ({ revision: ++calls });
  const [first, second] = await Promise.all([
    sharedControlRead("catalog", 1_000, load),
    sharedControlRead("catalog", 1_000, load),
  ]);
  assert.equal(calls, 1);
  assert.equal(first, second);
  assert.equal((await sharedControlRead("catalog", 1_000, load)).revision, 1);
  assert.equal(sharedControlReadCountForTests(), 1);
});

test("caller abort does not cancel the physical read shared by another Cell", async () => {
  resetSharedControlReadsForTests();
  const controller = new AbortController();
  let resolve!: (value: number) => void;
  const physical = new Promise<number>((done) => { resolve = done; });
  const cancelled = sharedControlRead("snapshot", 1_000, () => physical, controller.signal);
  const retained = sharedControlRead("snapshot", 1_000, () => physical);
  controller.abort();
  resolve(42);
  await assert.rejects(cancelled, { name: "AbortError" });
  assert.equal(await retained, 42);
});

test("failed and overflow entries are removed within the hard bound", async () => {
  resetSharedControlReadsForTests();
  await assert.rejects(sharedControlRead("failed", 1_000, async () => {
    throw new Error("boom");
  }), /boom/);
  assert.equal(sharedControlReadCountForTests(), 0);
  for (let index = 0; index < 40; index += 1) {
    await sharedControlRead(`key-${index}`, 1_000, async () => index);
  }
  assert.equal(sharedControlReadCountForTests(), 32);
});

for (const outcome of ["resolve", "reject"] as const) {
  test(`invalidated ${outcome} cannot replace or evict a newer cached read`, async () => {
    resetSharedControlReadsForTests();
    let resolve!: (value: string) => void;
    let reject!: (reason: Error) => void;
    const pending = new Promise<string>((done, fail) => { resolve = done; reject = fail; });
    const oldRead = sharedControlRead("plugin", 60_000, () => pending);
    const oldResult = oldRead.catch(() => "rejected");
    await sharedControlRead("unrelated", 60_000, async () => "retained");
    invalidateSharedControlRead("plugin");
    assert.equal(await sharedControlRead("plugin", 60_000, async () => "fresh"), "fresh");
    if (outcome === "resolve") resolve("old");
    else reject(new Error("old request failed"));
    await oldResult;
    assert.equal(await sharedControlRead("plugin", 60_000, async () => "unexpected reload"), "fresh");
    assert.equal(await sharedControlRead("unrelated", 60_000, async () => "unexpected reload"), "retained");
    assert.equal(sharedControlReadCountForTests(), 2);
  });
}
