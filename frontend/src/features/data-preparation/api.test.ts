import assert from "node:assert/strict";
import test from "node:test";
import { waitForPreparation, type PreparationJob } from "./api.js";

function running(): PreparationJob {
  return {
    id: "progressive-task", state: "RUNNING", stage: "FETCHING", completed: 1,
    total: 2, revision: 3, cancel_requested: false, error: null,
    request: { consumer: "REPLAY", progressive: true, requirements: [{ symbol: "BTCUSDT" }], intent: {} },
    result: { run: { run_id: "prepared-task", adapter_session_id: "session" } as NonNullable<NonNullable<PreparationJob["result"]>["run"]> },
  };
}

test("replay observer opens a committed prefix while download continues", async () => {
  const job = running();
  let polls = 0;
  const observed: PreparationJob[] = [];
  const fetcher: typeof fetch = async () => { polls++; throw new Error("unexpected poll"); };
  const ready = await waitForPreparation(job, item => observed.push(item), undefined, { fetcher }, true);
  assert.equal(ready, job);
  assert.equal(ready.state, "RUNNING");
  assert.equal(polls, 0);
  assert.deepEqual(observed, [job]);
});

test("ordinary preparation observer still waits for complete input", async () => {
  const job = running();
  let polls = 0;
  const fetcher: typeof fetch = async () => {
    polls++;
    return Response.json({ ...job, state: "READY", completed: 2 });
  };
  const ready = await waitForPreparation(job, () => {}, undefined, { fetcher });
  assert.equal(ready.state, "READY");
  assert.equal(polls, 1);
});

test("a failed tail is reported instead of accepting a stale run result", async () => {
  const job = { ...running(), state: "FAILED" as const,
    error: { code: "NETWORK", message: "Tail download failed", retryable: true } };
  await assert.rejects(waitForPreparation(job, () => {}, undefined, {}, true), /Tail download failed/);
});
