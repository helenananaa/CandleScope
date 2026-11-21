import assert from "node:assert/strict";
import test, { mock } from "node:test";
import type { StrategyRunStatus } from "../../runResult/strategyRun.js";
import type { NativeRun } from "../nativeBacktestApi.js";
import { watchNativeRun } from "../nativeRunWatch.js";

function status(state: StrategyRunStatus["state"], sourceState: string = state): StrategyRunStatus {
  const terminal = state === "COMPLETED" || state === "FAILED" || state === "CANCELLED";
  return { run_id: "native_1", family: "external", authority: "HOST", clock_policy: "FIXED", fidelity: "BAR_APPROX",
    language: "pine", state, source_state: sourceState, terminal, generation: null, result_available: state === "COMPLETED",
    error: null };
}

const queued = { run_id: "native_1", state: "QUEUED", execution_mode: "CANDLESCOPE", created_at_ms: 1 } as NativeRun;

function manager(statuses: StrategyRunStatus[]) {
  return {
    async watchRun(runId: string, onStatus?: (value: StrategyRunStatus) => void) {
      assert.equal(runId, "native_1");
      for (const value of statuses) onStatus?.(value, null);
      return statuses.at(-1)!;
    },
  };
}

test("state changes update the header and the finished record is read once", async () => {
  const requests: string[] = [];
  const record = { ...queued, state: "COMPLETED", result: { trades: [] } } as unknown as NativeRun;
  mock.method(globalThis, "fetch", async (input: RequestInfo | URL) => {
    requests.push(String(input));
    return Response.json(record);
  });
  try {
    const seen: string[] = [];
    const finished = await watchNativeRun(manager([status("QUEUED"), status("RUNNING"), status("RUNNING"), status("COMPLETED")]),
      queued, (run) => seen.push(run.state));
    assert.deepEqual(seen, ["RUNNING", "COMPLETED"]);
    assert.deepEqual(finished, record);
    assert.equal(requests.length, 1);
    assert.match(requests[0]!, /\/backtests\/external\/runs\/native_1$/);
  } finally {
    mock.restoreAll();
  }
});

test("a record that disagrees with the finished status is refused", async () => {
  mock.method(globalThis, "fetch", async () => Response.json({ ...queued, state: "RUNNING" }));
  try {
    await assert.rejects(watchNativeRun(manager([status("FAILED", "INTERRUPTED")]), queued, () => {}), /differs/);
  } finally {
    mock.restoreAll();
  }
});
