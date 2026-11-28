import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { defaultNativeRunClient, FOLLOW_OF_HEADER, loadShownNativeRun, type NativeRun } from "../nativeBacktestApi.js";

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

function recordFetch(): Array<{ url: string; init: RequestInit }> {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  globalThis.fetch = (async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return new Response(JSON.stringify({ run_id: "native_rebuild", state: "QUEUED" }), { status: 200 });
  }) as typeof fetch;
  return calls;
}

test("a FOLLOW rebuild names the user's run it rebuilds outside the run input (ADR O2)", async () => {
  const calls = recordFetch();
  const base = `native_${"a".repeat(32)}`;
  await defaultNativeRunClient.create("NATIVE", { source: "strategy" }, "follow-key", undefined, { followOf: base });
  await defaultNativeRunClient.create("CANDLESCOPE", { source: "strategy" }, "follow-key-2", undefined, { followOf: base });
  await defaultNativeRunClient.create("NATIVE", { source: "strategy" }, "user-key");
  const headers = calls.map((call) => call.init.headers as Record<string, string>);
  assert.equal(headers[0]![FOLLOW_OF_HEADER], base);
  assert.equal(headers[0]!["Idempotency-Key"], "follow-key");
  assert.match(calls[1]!.url, /\/backtests\/external\/runs$/);
  assert.equal(headers[1]![FOLLOW_OF_HEADER], base);
  assert.equal(FOLLOW_OF_HEADER in headers[2]!, false);
  assert.deepEqual(JSON.parse(String(calls[0]!.init.body)), { source: "strategy" });
});

const run = (runId: string) => ({ run_id: runId, state: "COMPLETED" }) as unknown as NativeRun;
const notFound = () => new Error(`Not Found\n${JSON.stringify({ error: { code: "RUN_NOT_FOUND", message: "native run not found" } })}`);

test("a cell whose FOLLOW result is no longer kept shows the user's own latest run", async () => {
  const loads: string[] = [];
  const shown = await loadShownNativeRun(async (runId) => {
    loads.push(runId);
    if (runId === "native_rebuild") throw notFound();
    return run(runId);
  }, "native_rebuild", "native_user");
  assert.equal(shown.run_id, "native_user");
  assert.deepEqual(loads, ["native_rebuild", "native_user"]);
});

test("other failures, and a cell without a run of its own, still report the error", async () => {
  await assert.rejects(loadShownNativeRun(async () => { throw notFound(); }, "native_rebuild", undefined), /RUN_NOT_FOUND/);
  await assert.rejects(loadShownNativeRun(async () => { throw new Error("Internal Server Error"); }, "native_rebuild", "native_user"),
    /Internal Server Error/);
  const loads: string[] = [];
  await assert.rejects(loadShownNativeRun(async (runId) => { loads.push(runId); throw notFound(); }, "native_user", "native_user"));
  assert.deepEqual(loads, ["native_user"]);
});
