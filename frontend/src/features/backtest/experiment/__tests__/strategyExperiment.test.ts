import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { parseStrategyExperiment, parseStrategyExperimentFrame, StrategyExperimentContractError,
  STRATEGY_EXPERIMENT_STREAM_SCHEMA } from "../strategyExperiment.js";
import { createBacktestApi } from "../../backtestApi.js";
import { StrategyDataManager } from "../../../market-data/manager/strategyDataManager.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const served = JSON.parse(readFileSync(path.resolve(here,
  "../../../../../tests/fixtures/strategy-experiment/running.strategy-experiment.json"), "utf8")) as Record<string, unknown>;

test("the experiment the backend serves parses with each member's own state", () => {
  const experiment = parseStrategyExperiment(served);
  assert.equal(experiment.experimentId, "ex_fixture");
  assert.equal(experiment.state, "RUNNING");
  assert.deepEqual(experiment.counts, { total: 3, completed: 1, failed: 1, cancelled: 0, active: 1 });
  assert.deepEqual(experiment.members.map((member) => member.state), ["PREPARING", "COMPLETED", "FAILED"]);
  assert.deepEqual(experiment.members[0]!.preparation && [experiment.members[0]!.preparation.completed, experiment.members[0]!.preparation.total], [2, 3]);
  assert.equal(experiment.members[1]!.runId, "bt_0");
  assert.equal(experiment.members[2]!.error?.code, "SOURCE_UNAVAILABLE");
  for (const broken of [{ ...served, schema: "other" }, { ...served, experiment_id: "bt_1" }, { ...served, state: "DONE" },
    { ...served, members: [{ ...(served.members as object[])[0], state: "WAITING" }] }]) {
    assert.throws(() => parseStrategyExperiment(broken), StrategyExperimentContractError);
  }
});

function ndjson(frames: unknown[]): Response {
  const body = frames.map((frame) => JSON.stringify(frame)).join("\n") + "\n";
  return new Response(body, { headers: { "content-type": "application/x-ndjson" } });
}

test("the manager follows an experiment's stream until no member is active, skipping heartbeats", async () => {
  const done = { ...served, state: "COMPLETED", counts: { total: 3, completed: 3, failed: 0, cancelled: 0, active: 0 },
    members: (served.members as Array<Record<string, unknown>>).map((member) => ({ ...member, state: "COMPLETED", error: null })) };
  const frames = [
    { schema: STRATEGY_EXPERIMENT_STREAM_SCHEMA, type: "status", terminal: false, experiment: served },
    { schema: STRATEGY_EXPERIMENT_STREAM_SCHEMA, type: "heartbeat", terminal: false },
    { schema: STRATEGY_EXPERIMENT_STREAM_SCHEMA, type: "status", terminal: true, experiment: done },
  ];
  const requested: string[] = [];
  const original = globalThis.fetch;
  globalThis.fetch = (async (input: RequestInfo | URL) => { requested.push(String(input)); return ndjson(frames); }) as typeof fetch;
  try {
    const manager = new StrategyDataManager(createBacktestApi("/api/v1/backtests", "/api/v1/strategy-runs"));
    const seen: string[] = [];
    const last = await manager.watchExperiment("ex_fixture", (value) => seen.push(value.state));
    assert.deepEqual(seen, ["RUNNING", "COMPLETED"]);
    assert.equal(last.state, "COMPLETED");
    assert.deepEqual(requested, ["/api/v1/strategy-experiments/ex_fixture/events"]);
  } finally {
    globalThis.fetch = original;
  }
  assert.equal(parseStrategyExperimentFrame({ schema: STRATEGY_EXPERIMENT_STREAM_SCHEMA, type: "heartbeat" }), null);
  assert.deepEqual(parseStrategyExperimentFrame({ schema: STRATEGY_EXPERIMENT_STREAM_SCHEMA, type: "error",
    error: { code: "EXPERIMENT_NOT_FOUND", message: "gone" } }), { error: { code: "EXPERIMENT_NOT_FOUND", message: "gone" } });
});
