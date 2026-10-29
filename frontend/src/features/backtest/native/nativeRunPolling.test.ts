import assert from "node:assert/strict";
import test from "node:test";
import { pollNativeRun } from "./nativeRunPolling.js";
import type { NativeRun } from "./nativeBacktestApi.js";

test("run polling retains its cached inputs only for the same run/state and fetches completed output", async () => {
  const current: NativeRun = { run_id:"run", execution_mode:"CANDLESCOPE", state:"RUNNING", created_at_ms:1,
    result:null, runtime_identity:{ engine:{ package:"pine", version:"test", code_sha256:"hash" } } };
  const originalFetch = globalThis.fetch;
  try {
    let reply: unknown = { ...current, run_unchanged:true };
    globalThis.fetch = async input => {
      assert.match(String(input), /external\/runs\/run\?if_state=RUNNING$/);
      return new Response(JSON.stringify(reply));
    };
    assert.deepEqual(await pollNativeRun(current), current);
    reply = { ...current, state:"COMPLETED" };
    assert.deepEqual(await pollNativeRun(current), reply);
    reply = { ...current, state:"COMPLETED", run_unchanged:true };
    await assert.rejects(pollNativeRun(current), /state differs/);
    reply = { ...current, run_id:"another", run_unchanged:true };
    await assert.rejects(pollNativeRun(current), /state differs/);
  } finally { globalThis.fetch = originalFetch; }
});
