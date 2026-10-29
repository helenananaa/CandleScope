import assert from "node:assert/strict";
import test from "node:test";
import { prepareReplay, preparationRequest, PreparationApiError, PreparedReplayDeletedError, waitForPreparation, type PreparationJob } from "./api.js";
import type { TrainingRunCreatePayload } from "../replay/replayV2Types.js";

function running(): PreparationJob {
  return {
    id: "progressive-task", state: "RUNNING", stage: "FETCHING", completed: 1,
    total: 2, revision: 3, cancel_requested: false, error: null,
    request: { consumer: "REPLAY", progressive: true, requirements: [{ symbol: "BTCUSDT" }], intent: {} },
    result: { run: { run_id: "prepared-task", adapter_session_id: "session" } as NonNullable<NonNullable<PreparationJob["result"]>["run"]> },
  };
}

test("preparation errors retain the actionable server code and HTTP status", async () => {
  await assert.rejects(preparationRequest("/replay", {}, { fetcher: async () => Response.json({
    detail: { code: "FUTURE_INPUT", message: "Only closed historical bars may be prepared" },
  }, { status: 409 }) }), error => error instanceof PreparationApiError
    && error.code === "FUTURE_INPUT" && error.status === 409);
});

test("request validation has an actionable code without exposing rejected inputs", async () => {
  await assert.rejects(preparationRequest("/strategy", {}, { fetcher: async () => Response.json({
    detail: [{ type: "extra_forbidden", loc: ["body", "strategy", "source"], input: "private script" }],
  }, { status: 422 }) }), error => error instanceof PreparationApiError
    && error.code === "DATA_PREPARATION_INVALID_REQUEST" && error.status === 422
    && !error.message.includes("private script"));
});

test("durable preparation failures retain their domain code after polling", async () => {
  const job = { ...running(), state: "FAILED" as const,
    error: { code: "PYTHON_PERMISSION_DENIED", message: "Confirm local execution", retryable: false } };
  await assert.rejects(waitForPreparation(job, () => {}), error => error instanceof PreparationApiError
    && error.code === "PYTHON_PERMISSION_DENIED" && error.message === "Confirm local execution");
});

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

test("READY preparation verifies the run before opening and distinguishes deletion from transport failure", async () => {
  const job = { ...running(), state: "READY" as const };
  const calls: string[] = [];
  let unavailable = false;
  const fetcher: typeof fetch = async input => {
    calls.push(String(input));
    if (String(input).endsWith("/data-preparations/replay")) return Response.json(job);
    if (unavailable) throw new Error("network offline");
    return Response.json({ protocol: "replay.v3", error: {
      code: "TRAINING_RUN_NOT_FOUND", message: "training run does not exist", details: {},
    } }, { status: 404 });
  };
  const submit = () => prepareReplay({} as TrainingRunCreatePayload,
    { exchange: "binance", market_type: "spot", symbol: "BTCUSDT" }, () => {}, undefined,
    "saved-submission", { fetcher, basePath: "http://fixture/api/v1/data-preparations" });
  await assert.rejects(submit(), PreparedReplayDeletedError);
  assert.deepEqual(calls, ["http://fixture/api/v1/data-preparations/replay", "http://fixture/api/v1/replay/runs/prepared-task"]);
  unavailable = true;
  await assert.rejects(submit(), error => !(error instanceof PreparedReplayDeletedError));
});

test("resubmitting a saved retryable failure retries the same durable job once", async () => {
  const failed = { ...running(), state: "FAILED" as const, result: null,
    error: { code: "INSTRUMENT_METADATA_UNAVAILABLE", message: "Catalog was not ready", retryable: true } };
  const run = { run_id: "prepared-task", kind: "V2", name: "Recovered training", state: "PAUSED",
    source_kind: "BAR", integrity_mode: "CHALLENGE", time_disclosure_policy: "NONE", last_symbol: "BTCUSDT",
    subscribed_track_count: 1, progress: { source_sequence: 0 }, equity: "10000", equity_status: "CURRENT",
    settlement_asset: "USDT", updated_at_ms: 1_800_000_000_000, compatibility: "READY",
    resume_action: "OPEN_ADAPTER", adapter_session_id: "session", status: { code: "READY", message: "Ready" },
    report_available: false, review_available: false };
  const calls: string[] = [];
  const fetcher: typeof fetch = async (input, options) => {
    const path = new URL(String(input)).pathname;
    calls.push(`${options?.method ?? "GET"} ${path}`);
    if (path.endsWith("/data-preparations/replay")) {
      assert.equal((JSON.parse(String(options?.body)) as { idempotency_key: string }).idempotency_key, "saved-key");
      return Response.json(failed);
    }
    if (path.endsWith("/progressive-task/retry")) return Response.json({ ...running(), state: "READY", result: { run } });
    if (path.endsWith("/runs/prepared-task")) return Response.json(run);
    throw new Error(`Unexpected ${path}`);
  };
  const result = await prepareReplay({} as TrainingRunCreatePayload,
    { exchange: "binance", market_type: "spot", symbol: "BTCUSDT" }, () => {}, undefined,
    "saved-key", { fetcher, basePath: "http://fixture/api/v1/data-preparations" });
  assert.equal(result.run.run_id, "prepared-task");
  assert.deepEqual(calls, ["POST /api/v1/data-preparations/replay",
    "POST /api/v1/data-preparations/progressive-task/retry", "GET /api/v1/replay/runs/prepared-task"]);
});

test("an explicit replay retry is bounded and does not restart cancelled or non-retryable jobs", async () => {
  for (const state of ["FAILED", "CANCELLED", "BLOCKED_STORAGE"] as const) {
    for (const retryable of [false, true]) {
      const failed = { ...running(), state, result: null,
        error: { code: "UNAVAILABLE", message: "Still unavailable", retryable } };
      const paths: string[] = [];
      const fetcher: typeof fetch = async input => { paths.push(String(input)); return Response.json(failed); };
      await assert.rejects(prepareReplay({} as TrainingRunCreatePayload,
        { exchange: "binance", market_type: "spot", symbol: "BTCUSDT" }, () => {}, undefined,
        "saved-key", { fetcher, basePath: "http://fixture/api/v1/data-preparations" }), /Still unavailable/);
      assert.equal(paths.length, state === "FAILED" && retryable ? 2 : 1);
      if (paths.length === 2) assert.ok(paths[1]?.endsWith("/progressive-task/retry"));
    }
  }
});
