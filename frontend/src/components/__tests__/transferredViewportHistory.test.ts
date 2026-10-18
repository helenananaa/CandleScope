import assert from "node:assert/strict";
import test from "node:test";
import { TransferredViewportHistory } from "../transferredViewportHistory.js";

const ready = (firstTime: number) => ({ datasetKey: "fine", firstTime, loading: false, canLoad: true, hasHandler: true });

test("viewport fill requests contiguous pages serially and stops at the visible left edge", () => {
  const fill = new TransferredViewportHistory("fine", 100);
  assert.equal(fill.claim(ready(900)), 900);
  assert.equal(fill.claim(ready(400)), null);
  fill.settle(true);
  assert.equal(fill.claim(ready(400)), 400);
  fill.settle(true);
  assert.equal(fill.claim(ready(0)), null);
  assert.equal(fill.claim(ready(900)), null);
});

test("viewport fill waits for target ownership and initial loading without issuing old-dataset requests", () => {
  const fill = new TransferredViewportHistory("fine", 100);
  assert.equal(fill.claim({ ...ready(900), datasetKey: "coarse" }), null);
  assert.equal(fill.claim({ ...ready(900), loading: true }), null);
  assert.equal(fill.claim({ ...ready(900), firstTime: undefined }), null);
  assert.equal(fill.claim(ready(900)), 900);
});

test("exhaustion, failure, repeated boundary and page budget cannot spin", () => {
  for (const mode of ["exhausted", "failed", "unchanged", "budget"] as const) {
    const fill = new TransferredViewportHistory("fine", 0, mode === "budget" ? 1 : 20);
    assert.equal(fill.claim(ready(900)), 900);
    fill.settle(mode !== "failed");
    assert.equal(fill.claim({ ...ready(mode === "unchanged" ? 900 : 400), canLoad: mode !== "exhausted" }), null);
    assert.equal(fill.claim(ready(100)), null);
  }
});

test("the production loader boundary never converts a stop or wait signal into a request at epoch zero", async () => {
  const calls: number[] = [];
  const load = async (before: number) => { calls.push(before); };
  const fill = new TransferredViewportHistory("fine", 100);
  assert.equal(await fill.loadPage({ ...ready(900), loading: true }, load), false);
  assert.equal(await fill.loadPage({ ...ready(900), datasetKey: "old" }, load), false);
  assert.deepEqual(calls, []);
  assert.equal(await fill.loadPage(ready(900), load), true);
  assert.equal(await fill.loadPage(ready(400), load), true);
  assert.equal(await fill.loadPage(ready(0), load), false);
  assert.equal(await fill.loadPage(ready(900), load), false);
  assert.deepEqual(calls, [900, 400]);
});
