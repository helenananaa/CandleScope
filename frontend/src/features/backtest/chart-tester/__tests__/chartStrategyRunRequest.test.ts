import assert from "node:assert/strict";
import test from "node:test";

import { BacktestApiError, type ChartContextResolution, type StrategyRevisionRecord } from "../../backtestApi.js";
import type { BacktestResultReplayFrame, BacktestRunRecord } from "../../backtestTypes.js";
import { StrategyRunStreamError } from "../../backtestRunStream.js";
import {
  buildChartStrategyRunBody,
  chartStrategyQuickPresetIdForMarket,
  chartStrategyRunDiagnostics,
  freezeChartStrategyRunRequest,
  qualitySummaryFromImportedManifest,
  runChartStrategyBacktest,
  runResearchBacktest,
  type ChartStrategyRunApi,
} from "../chartStrategyRunRequest.js";
import type { ChartStrategyRunRequest } from "../chartStrategyTesterUiModel.js";
import { StrategyDataManager, type StrategyDataApi } from "../../../market-data/manager/strategyDataManager.js";

const request: ChartStrategyRunRequest = {
  cellScope: "workspace\u0000cell-1",
  session: {
    exchange: "binance",
    marketType: "usdm",
    symbol: "BTCUSDT",
    interval: "1h",
  },
  draftId: "draft-12345678",
  draftContentRevision: 1,
  displayName: "SMA Cross",
  language: "pine",
  source: [
    'strategy("SMA Cross")',
    "fast = sma(close, 3)",
    "slow = sma(close, 5)",
    "if crossover(fast, slow)",
    "  target_position(1)",
  ].join("\n"),
  attachment: {
    schemaVersion: 1,
    strategyDraftId: "draft-12345678",
    strategyRevisionId: null,
    displayName: "SMA Cross",
    language: "pine",
    parameters: { fast: 3, slow: 5 },
    rangeMode: "ALL_AVAILABLE",
    customRange: null,
    fidelityPreference: "FAST",
    quickPresetId: "CRYPTO_PERP_STANDARD_V1",
    autoRun: false,
  },
};

test("Pine libraries are frozen into revision dependencies and excluded from input overrides", async () => {
  const libraries = { "local/Math/1": '//@version=6\nlibrary("Math")\nexport twice(float x) => x * 2' };
  const input = { ...request, language: "pine" as const, attachment: { ...request.attachment, language: "pine" as const,
    parameters: { length: 5, __pineLibrariesText: JSON.stringify(libraries) } } };
  const frozen = await freezeChartStrategyRunRequest(input);
  assert.deepEqual(frozen.attachment.parameters, { length: 5, __pineLibraries: libraries });
  const changed = await freezeChartStrategyRunRequest({ ...input, attachment: { ...input.attachment, parameters: { ...input.attachment.parameters, __pineLibrariesText: JSON.stringify({ "local/Math/1": libraries["local/Math/1"].replace("x * 2", "x * 3") }) } } });
  assert.notEqual(changed.parameterHash, frozen.parameterHash);
  await assert.rejects(freezeChartStrategyRunRequest({ ...input, attachment: { ...input.attachment, parameters: { __pineLibrariesText: "[" } } }));
  const api = apiWithResolutions([resolution(), resolution()], []);
  const create = api.createStrategyRevision;
  api.createStrategyRevision = async (body, signal) => { assert.deepEqual(body.libraries, libraries); return create(body, signal); };
  api.smokeStrategyRevision = async (_revision, body) => { assert.deepEqual(body.parameters, { length: 5 }); return { ok: true }; };
  api.createRun = async (body) => { assert.deepEqual(body.parameters, { length: 5 }); return completed(); };
  await runChartStrategyBacktest({ api, request: input });
});

test("Python requires current-source consent before compilation and carries runtime mode through smoke and Run", async () => {
  const python = { ...request, language: "python" as const, attachment: { ...request.attachment, language: "python" as const } };
  const calls: string[] = [];
  const api = apiWithResolutions([resolution(), resolution()], calls);
  await assert.rejects(runChartStrategyBacktest({ api, request: python }), /Confirm local Python/);
  assert.deepEqual(calls, []);
  api.smokeStrategyRevision = async (_revision, body) => {
    assert.equal(body.python_runtime_mode, "TRUSTED_LOCAL");
    assert.equal(body.python_trusted_confirmed, true);
    return { ok: true };
  };
  api.createRun = async (body) => {
    assert.equal(body.python_runtime_mode, "TRUSTED_LOCAL");
    assert.equal(body.python_trusted_confirmed, true);
    return completed();
  };
  await runChartStrategyBacktest({ api, request: { ...python, pythonTrustedConfirmed: true } });
  assert.equal(calls[0], "revision:PYTHON_EDITOR");
});

test("Python permissions reach automatic data preparation and its server-created Run", async () => {
  const calls: string[] = [];
  const api = apiWithResolutions([resolution("NEEDS_DATA")], calls);
  api.prepareChartContext = async (_body, _signal, intent) => {
    assert.equal(intent?.python_runtime_mode, "TRUSTED_LOCAL");
    assert.equal(intent?.python_trusted_confirmed, true);
    return { ...resolution(), prepared_run: completed() };
  };
  const result = await runChartStrategyBacktest({ api, request: { ...request, language: "python", pythonTrustedConfirmed: true, attachment: { ...request.attachment, language: "python" } } });
  assert.equal(result.kind, "TERMINAL");
});

test("custom conditions are frozen into the actual request with explicit fee provenance", async () => {
  const executionOverrides = { initialBalance: "2000", equityPercent: "25", leverage: "2", feeBps: "7", slippageBps: "3" };
  const frozen = await freezeChartStrategyRunRequest({ ...request, attachment: { ...request.attachment, executionOverrides } });
  executionOverrides.initialBalance = "9000";
  const body = buildChartStrategyRunBody({ frozen, revision, resolution: resolution() });
  assert.equal(body.initial_balance, "2000");
  assert.equal(body.equity_percent, "25");
  assert.equal(body.leverage, "2");
  assert.equal(body.taker_fee_bps, "7");
  assert.equal(body.slippage_bps, "3");
  assert.equal(body.fee_source, "user-defined");
  await assert.rejects(freezeChartStrategyRunRequest({ ...request, attachment: { ...request.attachment, executionOverrides: { ...executionOverrides, leverage: "0" } } }));
});

const revision: StrategyRevisionRecord = {
  revision_id: "srv2_chart",
  provider_kind: "PINE_SUBSET",
  language: "PINE_SUBSET",
  label: "SMA Cross",
  description: "immutable",
  input_modes: ["BAR_CLOSE"],
  output_modes: ["TARGET_POSITION"],
  signal_clock: "EVENT",
  required_features: [],
  warmup_requirement: {},
  parameter_schema: [],
  accepts_source: false,
  source_hash: "sha256:source",
  compiled_hash: "sha256:compiled",
  runtime_revision: "candlescope-strategy-workspace/2",
  reused: false,
};

function resolution(
  status: ChartContextResolution["status"] = "READY",
  suffix = "a",
): ChartContextResolution {
  return {
    schema_version: "candlescope.backtest-chart-context/1",
    status,
    resolution_token: `token-${suffix.padEnd(20, suffix)}`,
    chart_context_hash: `sha256:context-${suffix}`,
    expires_at_ms: 999_999,
    request: {
      exchange: "binance",
      market_type: "usdm",
      symbol: "BTCUSDT",
      interval: "1h",
      range_mode: "ALL_AVAILABLE",
      start_time_ms: null,
      end_time_ms: null,
      fidelity_preference: "FAST",
    },
    dataset_id: status === "READY" ? "local-chart" : null,
    data_epoch: status === "READY" ? "epoch-20260824" : null,
    snapshot_hash: status === "READY" ? `sha256:snapshot-${suffix}` : null,
    coverage: {
      requested_start_ms: status === "READY" ? 1_000 : null,
      requested_end_ms: status === "READY" ? 3_601_000 : null,
      available_start_ms: status === "READY" ? 1_000 : null,
      available_end_ms: status === "READY" ? 3_601_000 : null,
      row_count: status === "READY" ? 2 : null,
      missing_ranges: [],
      complete: status === "READY",
    },
    fidelity: { preference: "FAST", mode: "BAR_APPROX", capabilities: ["BAR_APPROX"] },
    quality_warnings: [],
    quick_preset_id: "CRYPTO_PERP_STANDARD_V1",
    cost_preset: {
      preset_id: "CRYPTO_PERP_STANDARD_V1",
      preset_revision: "1",
      fee_source: "exchange-market-preset",
      fee_bps: "4",
      slippage_bps: "1",
    },
    account_execution_preset: {
      account_model: "LINEAR_PERP_ONE_WAY_V1",
      sizing_policy: "EQUITY_PERCENT_V1",
      equity_percent: "10",
      initial_cash: "10000",
      leverage: "1",
      execution_model_revision: "EXECUTION_REALISM_V2",
      contract_data_mode: "LEGACY_FIXED_V1",
      funding_mode: "OFF",
    },
    materialize: {
      required: status === "NEEDS_DATA",
      estimated_bars: status === "NEEDS_DATA" ? 24 : 0,
    },
  };
}

function completed(): BacktestRunRecord {
  return {
    run_id: "bt_chart",
    state: "COMPLETED",
    fidelity_mode: "BAR_APPROX",
    source_event_kind: "BAR",
    config_hash: "sha256:config",
  };
}

function apiWithResolutions(
  values: ChartContextResolution[],
  calls: string[],
  keys: string[] = [],
): ChartStrategyRunApi {
  let index = 0;
  return {
    async createStrategyRevision(body) {
      calls.push(`revision:${String(body.language)}`);
      return revision;
    },
    async resolveChartContext() {
      calls.push("resolve");
      return values[Math.min(index++, values.length - 1)]!;
    },
    async materializeChartContext(body) {
      calls.push(`materialize:${body.user_confirmed}`);
      return values[Math.min(index, values.length - 1)]!;
    },
    async smokeStrategyRevision() {
      calls.push("smoke");
      return { ok: true };
    },
    async validate() {
      calls.push("validate");
      return { ok: true };
    },
    async createRun(_body, key) {
      calls.push("create");
      keys.push(key);
      return { ...completed(), state: "QUEUED" };
    },
    async getRun() {
      calls.push("get");
      return completed();
    },
  };
}

test("freezes source/parameters and creates a stable expanded quick Run", async () => {
  const frozen = await freezeChartStrategyRunRequest(request);
  assert.match(frozen.parameterHash, /^sha256:[0-9a-f]{64}$/);
  assert.notEqual(frozen.attachment.parameters, request.attachment.parameters);
  const body = buildChartStrategyRunBody({ frozen, revision, resolution: resolution() });
  assert.equal(body.strategy_revision_id, revision.revision_id);
  assert.equal(body.taker_fee_bps, "4");
  assert.equal(body.maker_fee_bps, "4");
  assert.equal(body.quick_preset_revision, "1");
  assert.equal(body.dataset_id, "local-chart");
  assert.equal(body.strategy_source, undefined);
  assert.equal(body.chart_cell_scope, request.cellScope);
  assert.equal(body.strategy_draft_id, request.draftId);
});

test("freezes the market fee preset from the session, not a stale attachment", async () => {
  assert.equal(chartStrategyQuickPresetIdForMarket("spot"), "CRYPTO_SPOT_STANDARD_V1");
  assert.equal(chartStrategyQuickPresetIdForMarket("usdm"), "CRYPTO_PERP_STANDARD_V1");
  const frozen = await freezeChartStrategyRunRequest({
    ...request,
    session: { ...request.session, marketType: "spot" },
  });
  assert.equal(frozen.attachment.quickPresetId, "CRYPTO_SPOT_STANDARD_V1");
  const spotResolution = resolution();
  spotResolution.request = { ...spotResolution.request, market_type: "spot" };
  spotResolution.quick_preset_id = "CRYPTO_SPOT_STANDARD_V1";
  spotResolution.cost_preset = {
    ...spotResolution.cost_preset,
    preset_id: "CRYPTO_SPOT_STANDARD_V1",
  };
  const body = buildChartStrategyRunBody({
    frozen,
    revision,
    resolution: spotResolution,
  });
  assert.equal(body.quick_preset_id, "CRYPTO_SPOT_STANDARD_V1");
});

test("READY follows revision-resolve-smoke-validate-reresolve-create-poll", async () => {
  const calls: string[] = [];
  const keys: string[] = [];
  const api = apiWithResolutions([resolution(), resolution()], calls, keys);
  const outcome = await runChartStrategyBacktest({
    api,
    request,
    pollIntervalMs: 0,
  });
  assert.equal(outcome.kind, "TERMINAL");
  assert.deepEqual(calls, [
    "revision:PINE_ENGINE",
    "resolve",
    "smoke",
    "validate",
    "resolve",
    "create",
    "get",
  ]);
  assert.match(keys[0]!, /^chart-run:[0-9a-f]{64}$/);
  const secondCalls: string[] = [];
  await runChartStrategyBacktest({
    api: apiWithResolutions([resolution(), resolution()], secondCalls, keys),
    request,
    pollIntervalMs: 0,
  });
  assert.equal(keys[0], keys[1]);
});

test("Pine charts compile through the real engine revision rather than the frozen example subset", async () => {
  const calls: string[] = [];
  const pine: ChartStrategyRunRequest = { ...request, language: "pine",
    source: '//@version=6\nstrategy("SMA")\nif close > ta.sma(close, 2)\n    strategy.entry("L", strategy.long)',
    attachment: { ...request.attachment, language: "pine" } };
  const outcome = await runChartStrategyBacktest({ api: apiWithResolutions([resolution(), resolution()], calls),
    request: pine, pollIntervalMs: 0 });
  assert.equal(outcome.kind, "TERMINAL");
  assert.equal(calls[0], "revision:PINE_ENGINE");
});

test("Pine requested datasets are frozen into manual and automatically prepared runs", async (context) => {
  const previousFetch = globalThis.fetch;
  context.after(() => { globalThis.fetch = previousFetch; });
  const dataset = { dataset_id: "remote", data_epoch: "remote-epoch", name: "ETH", symbol: "ETHUSDT",
    interval: "2m", first_open_ms: 0, last_close_ms: 599999, exchange: "okx", market_type: "spot" };
  const signal = new AbortController().signal;
  globalThis.fetch = async (url, options) => {
    assert.equal(options?.signal, signal);
    if (String(url).endsWith("/datasets")) return new Response(JSON.stringify({ datasets: [dataset] }));
    assert.ok(String(url).endsWith("/datasets/snapshot"));
    const body = JSON.parse(String(options?.body)) as Record<string, unknown>;
    assert.equal(body.exchange, "okx"); assert.equal(body.market_type, "spot");
    return new Response(JSON.stringify({ snapshot_hash: "remote-snapshot" }));
  };
  const pine: ChartStrategyRunRequest = { ...request, language: "pine", attachment: {
    ...request.attachment, language: "pine", parameters: { length: 5, __pineInputs: {
      contexts: [{ dataset, symbol: "OKX:ETHUSDT" }], magnifier: null, libraries: "{}",
    } },
  } };
  const calls: string[] = [];
  const api = apiWithResolutions([resolution(), resolution()], calls);
  api.createStrategyRevision = async () => ({ ...revision, language: "PINE_ENGINE", output_modes: ["TARGET_POSITION", "ORDER_INTENT"] });
  api.createRun = async (body) => {
    assert.deepEqual(body.parameters, { length: 5 });
    assert.equal(body.output_mode, "ORDER_INTENT");
    assert.equal((body.pine_contexts as Record<string, unknown>[])[0]?.snapshot_hash, "remote-snapshot");
    assert.equal((body.pine_contexts as Record<string, unknown>[])[0]?.exchange, "okx");
    return completed();
  };
  assert.equal((await runChartStrategyBacktest({ api, request: pine, signal, pollIntervalMs: 0 })).kind, "TERMINAL");
  const automatic = apiWithResolutions([resolution("NEEDS_DATA")], []);
  automatic.createStrategyRevision = api.createStrategyRevision;
  automatic.prepareChartContext = async (_body, _signal, intent) => {
    assert.deepEqual(intent?.parameters, { length: 5 });
    assert.equal(intent?.output_mode, "ORDER_INTENT");
    assert.equal((intent?.pine_contexts?.[0] as Record<string, unknown>).snapshot_hash, "remote-snapshot");
    return { ...resolution(), prepared_run: completed() };
  };
  assert.equal((await runChartStrategyBacktest({ api: automatic, request: pine, signal, pollIntervalMs: 0 })).kind, "TERMINAL");
});

test("an idempotent completed Run is reused without polling or retry", async () => {
  const calls: string[] = [];
  const api = apiWithResolutions([resolution(), resolution()], calls);
  api.createRun = async () => {
    calls.push("create");
    return completed();
  };
  api.getRun = async () => {
    calls.push("get");
    return completed();
  };
  const outcome = await runChartStrategyBacktest({ api, request, pollIntervalMs: 0 });
  assert.equal(outcome.kind, "TERMINAL");
  assert.equal(outcome.kind === "TERMINAL" ? outcome.run.state : null, "COMPLETED");
  assert.equal(calls.filter((call) => call === "create").length, 1);
  assert.equal(calls.includes("get"), false);
});

test("NEEDS_DATA stops for confirmation and materialize always re-resolves", async () => {
  const needs = resolution("NEEDS_DATA");
  const firstCalls: string[] = [];
  const first = await runChartStrategyBacktest({
    api: apiWithResolutions([needs], firstCalls),
    request,
  });
  assert.equal(first.kind, "NEEDS_DATA");
  assert.deepEqual(firstCalls, ["revision:PINE_ENGINE", "resolve"]);

  const nextCalls: string[] = [];
  const next = await runChartStrategyBacktest({
    api: apiWithResolutions([resolution(), resolution()], nextCalls),
    request,
    materializeResolution: needs,
    pollIntervalMs: 0,
  });
  assert.equal(next.kind, "TERMINAL");
  assert.deepEqual(nextCalls.slice(0, 3), [
    "revision:PINE_ENGINE",
    "materialize:true",
    "resolve",
  ]);
});

test("automatic preparation carries frozen strategy intent and observes the server-created run", async () => {
  const calls: string[] = [];
  const api = apiWithResolutions([resolution("NEEDS_DATA")], calls);
  api.prepareChartContext = async (_context, _signal, intent) => {
    calls.push("prepare");
    assert.equal(intent?.strategy_revision_id, revision.revision_id);
    assert.deepEqual(intent?.parameters, request.attachment.parameters);
    assert.equal(intent?.strategy_draft_id, request.draftId);
    return { ...resolution(), prepared_run: { ...completed(), state: "QUEUED" } };
  };
  const outcome = await runChartStrategyBacktest({ api, request, pollIntervalMs: 0 });
  assert.equal(outcome.kind, "TERMINAL");
  assert.deepEqual(calls, ["revision:PINE_ENGINE", "resolve", "prepare", "get"]);
});

test("validate/create drift fails before create", async () => {
  const calls: string[] = [];
  await assert.rejects(
    runChartStrategyBacktest({
      api: apiWithResolutions([resolution("READY", "a"), resolution("READY", "b")], calls),
      request,
      pollIntervalMs: 0,
    }),
    (error: unknown) => (
      error instanceof Error
      && "code" in error
      && error.code === "CHART_CONTEXT_CHANGED"
    ),
  );
  assert.equal(calls.includes("create"), false);
});

test("unknown fees fail closed and provider diagnostics remain located", async () => {
  const frozen = await freezeChartStrategyRunRequest(request);
  const missingFee = resolution();
  delete missingFee.cost_preset.fee_source;
  assert.throws(
    () => buildChartStrategyRunBody({ frozen, revision, resolution: missingFee }),
    /fee_source/,
  );
  const error = new BacktestApiError(
    "PROVIDER_PROTOCOL_VIOLATION",
    'compile failed: [{"line":8,"column":19,"message":"unknown target"}]',
    { next_step: "fix source" },
    409,
  );
  const diagnostics = chartStrategyRunDiagnostics(error);
  assert.equal(diagnostics.action, "fix-strategy");
  assert.deepEqual(diagnostics.sourceDiagnostics[0], {
    line: 8,
    column: 19,
    message: "unknown target",
  });
});

test("backend Run capacity is actionable and never hidden behind generic retry", () => {
  const diagnostics = chartStrategyRunDiagnostics(new BacktestApiError(
    "RUN_CAPACITY_EXCEEDED",
    "backtest Run capacity is temporarily exhausted",
    { retryable: true, retry_after_ms: 1000 },
    429,
  ));
  assert.equal(diagnostics.action, "wait-and-retry");
  assert.equal(diagnostics.details.retryable, true);
  assert.equal(diagnostics.details.retry_after_ms, 1000);
});

const importedSource = {
  kind: "IMPORTED_DATASET" as const,
  datasetId: "local-0123456789abcdef0123456789abcdef",
  dataEpoch: "sha256:" + "a".repeat(64),
  interval: "15m",
  symbol: "BTC-USDT",
  startTimeMs: 1_704_067_200_000,
  endTimeMs: 1_704_076_800_000,
  quality: qualitySummaryFromImportedManifest({
    rows: 96,
    excludedRangeCount: 0,
    volumeAvailable: true,
  }),
};

function importedPreview(epoch = importedSource.dataEpoch) {
  return {
    data_epoch: epoch,
    snapshot_hash: "sha256:" + "c".repeat(64),
    coverage_start_ms: importedSource.startTimeMs,
    coverage_end_ms: importedSource.endTimeMs,
    row_count: 96,
    fidelity_capabilities: ["BAR_APPROX"],
    quality: { status: "ok", gap_count: 0, volume_available: true },
  };
}

function importedApi(calls: string[], epoch = importedSource.dataEpoch): ChartStrategyRunApi {
  return {
    ...apiWithResolutions([], calls),
    async previewSnapshot() {
      calls.push("preview");
      return importedPreview(epoch);
    },
  };
}

test("fixed-history DataManager owns the actual research stream without Run polling", async () => {
  const calls: string[] = [], states: string[] = [];
  const api: StrategyDataApi = {
    ...importedApi(calls),
    async getRun() { throw new Error("Research must not poll the Run endpoint"); },
    async getReport() { throw new Error("Result loading is a separate operation"); },
    async getChart() { throw new Error("Result loading is a separate operation"); },
    async cancelRun() { throw new Error("Releasing a consumer must not cancel execution"); },
    async listRuns() { throw new Error("Run history is a separate operation"); },
    async compareRuns() { throw new Error("Run comparison is a separate operation"); },
    async streamRun(runId, signal, onUpdate) {
      calls.push("stream");
      assert.equal(runId, completed().run_id);
      assert.equal(signal?.aborted, false);
      onUpdate?.({ type: "progress", run: { ...completed(), state: "RUNNING" }, progress: null });
      onUpdate?.({ type: "completed", run: completed(), progress: null });
      return completed();
    },
  };
  const manager = new StrategyDataManager(api);
  const outcome = await manager.runResearch({ request, source: importedSource, onRunUpdate: run => states.push(run.state) });
  assert.equal(outcome.kind, "TERMINAL");
  assert.equal(outcome.kind === "TERMINAL" && outcome.run.state, "COMPLETED");
  assert.equal(outcome.frozenContext?.snapshotHash, importedPreview().snapshot_hash);
  assert.equal(calls.filter(call => call === "stream").length, 1);
  assert.deepEqual(states, ["RUNNING", "COMPLETED"]);
  assert.equal(manager.diagnostics().operations, 0);
  assert.equal(manager.diagnostics().streams, 0);
  manager.dispose();
});

test("committed provider failure retains its code, reason and recovery action in research diagnostics", () => {
  const failure = chartStrategyRunDiagnostics(new StrategyRunStreamError("PROVIDER_CRASH_UNRECOVERABLE", "strategy crashed at sequence 12"));
  assert.equal(failure.code, "PROVIDER_CRASH_UNRECOVERABLE");
  assert.equal(failure.message, "strategy crashed at sequence 12");
  assert.equal(failure.action, "fix-strategy");
});

test("imported dataset previews and freezes without materialize or online resolve", async () => {
  const calls: string[] = [];
  const outcome = await runResearchBacktest({
    api: importedApi(calls),
    request: { ...request, session: { ...request.session, marketType: "spot", symbol: "BTC-USDT", interval: "15m" } },
    source: importedSource,
    pollIntervalMs: 0,
  });
  assert.equal(outcome.kind, "TERMINAL");
  assert.equal(outcome.frozenContext?.sourceKind, "IMPORTED_DATASET");
  assert.equal(outcome.frozenContext?.snapshotHash, importedPreview().snapshot_hash);
  assert.equal(outcome.frozenContext?.datasetId, importedSource.datasetId);
  assert.equal(outcome.kind === "TERMINAL" ? outcome.identity.frozenContextHash : "", outcome.frozenContext?.contextHash);
  assert.equal(outcome.resolution.fidelity.mode, "BAR_APPROX");
  assert.equal(outcome.resolution.materialize.required, false);
  assert.equal(outcome.resolution.cost_preset?.preset_revision, "2");
  assert.equal(outcome.resolution.account_execution_preset?.account_model, "SPOT_CASH_V1");
  assert.deepEqual(calls, [
    "revision:PINE_ENGINE",
    "preview",
    "smoke",
    "validate",
    "preview",
    "create",
    "get",
  ]);
  assert.equal(calls.includes("resolve"), false);
  assert.equal(calls.includes("materialize:true"), false);
});

test("imported data epoch change after preview fails before create", async () => {
  const calls: string[] = [];
  let previews = 0;
  const api = importedApi(calls);
  api.previewSnapshot = async () => {
    previews += 1;
    calls.push("preview");
    return importedPreview(previews === 1 ? importedSource.dataEpoch : `sha256:${"d".repeat(64)}`);
  };
  await assert.rejects(
    () => runResearchBacktest({
      api,
      request,
      source: importedSource,
      pollIntervalMs: 0,
    }),
    (error: unknown) => error instanceof Error && "code" in error && error.code === "DATA_SNAPSHOT_MISMATCH",
  );
  assert.equal(calls.includes("create"), false);
});

test("gapped imported windows are not READY and never create a Run", async () => {
  const calls: string[] = [];
  const outcome = await runResearchBacktest({
    api: importedApi(calls),
    request,
    source: {
      ...importedSource,
      quality: qualitySummaryFromImportedManifest({
        rows: 96,
        excludedRangeCount: 2,
        volumeAvailable: true,
      }),
    },
    pollIntervalMs: 0,
  });
  assert.equal(outcome.kind, "UNSUPPORTED");
  assert.equal(outcome.resolution.status, "UNAVAILABLE");
  assert.equal(outcome.resolution.coverage.complete, false);
  assert.equal(outcome.resolution.coverage.missing_ranges.length, 1);
  assert.equal(calls.includes("create"), false);
});

const preciseRequest = {
  ...request,
  attachment: {
    ...request.attachment,
    fidelityPreference: "PRECISE" as const,
    rangeMode: "CUSTOM" as const,
    customRange: { startMs: Date.UTC(2026, 9, 24, 23), endMs: Date.UTC(2026, 9, 25) },
  },
};

test("precise research never launches an estimated snapshot", async () => {
  const calls: string[] = [];
  const api = apiWithResolutions([resolution()], calls);
  api.prepareChartContext = async () => assert.fail("unexpected preparation of an estimated snapshot");
  await assert.rejects(
    runResearchBacktest({ api, request: preciseRequest, source: { kind: "CURRENT_CHART" } }),
    /resolved snapshot lacks aggregate-trade fidelity/,
  );
  assert.deepEqual(calls, ["revision:PINE_ENGINE", "resolve"]);
});

test("precise research prepares and archives the trade snapshot without manual BAR materialization", async () => {
  const calls: string[] = [];
  const unresolved = resolution("NEEDS_DATA");
  const api = apiWithResolutions([unresolved], calls);
  api.prepareChartContext = async (context) => {
    assert.equal(context.fidelity_preference, "PRECISE");
    assert.equal(context.end_time_ms, preciseRequest.attachment.customRange.endMs - 1);
    return {
      ...resolution(),
      request: context,
      fidelity: { preference: "PRECISE", mode: "AGG_TRADE_EXECUTION", capabilities: ["AGG_TRADE_EXECUTION"] },
      prepared_run: { ...completed(), fidelity_mode: "AGG_TRADE_EXECUTION", source_event_kind: "AGG_TRADE" },
    };
  };
  const outcome = await runResearchBacktest({
    api, request: preciseRequest, source: { kind: "CURRENT_CHART", materializeResolution: unresolved },
  });
  assert.equal(outcome.kind, "TERMINAL");
  assert.equal(outcome.resolution.fidelity.mode, "AGG_TRADE_EXECUTION");
  assert.equal(outcome.frozenContext?.capabilitySummary.fidelityCeiling, "TRADE_TAPE");
  assert.deepEqual(calls, ["revision:PINE_ENGINE", "resolve"]);
  const prepare = api.prepareChartContext;
  const mismatchApi = apiWithResolutions([unresolved], []);
  mismatchApi.prepareChartContext = async (context, signal, intent, key) => ({
    ...await prepare(context, signal, intent, key),
    prepared_run: completed(),
  });
  await assert.rejects(
    runResearchBacktest({ api: mismatchApi, request: preciseRequest, source: { kind: "CURRENT_CHART" } }),
    /run was not created with aggregate-trade fidelity/,
  );
});

test("precise research surfaces missing verified coverage when automatic preparation is unavailable", async () => {
  const api = apiWithResolutions([resolution("NEEDS_DATA")], []);
  await assert.rejects(
    runResearchBacktest({ api, request: preciseRequest, source: { kind: "CURRENT_CHART" } }),
    /Verified aggregate-trade coverage is unavailable/,
  );
});

test("imported precise fidelity is rejected as BAR_ONLY", async () => {
  const calls: string[] = [];
  await assert.rejects(
    () => runResearchBacktest({
      api: importedApi(calls),
      request: preciseRequest,
      source: importedSource,
    }),
    (error: unknown) => error instanceof Error && "code" in error && error.code === "FIDELITY_UNSUPPORTED",
  );
  assert.deepEqual(calls, []);
});

test("user market trades bind the local spot snapshot and never use online preparation", async () => {
  const calls: string[] = [];
  const api = importedApi(calls);
  const source = { ...importedSource, marketTradeInput: true };
  const precise = { ...preciseRequest, session: { ...preciseRequest.session, marketType: "spot" } };
  api.previewSnapshot = async (body) => {
    calls.push("preview");
    assert.equal(body.exchange, "local");
    assert.equal(body.account_model, "SPOT_CASH_V1");
    assert.equal(body.fidelity_mode, "AGG_TRADE_EXECUTION");
    return { ...importedPreview(), fidelity_capabilities: ["AGG_TRADE_EXECUTION"],
      quality: { source_quality: "user_market_trades" } };
  };
  api.createRun = async (body) => {
    calls.push("create");
    assert.equal(body.dataset_id, source.datasetId);
    assert.equal(body.data_epoch, source.dataEpoch);
    assert.equal(body.source_event_kind, "AGG_TRADE");
    assert.equal(body.fidelity_mode, "AGG_TRADE_EXECUTION");
    return { ...completed(), source_event_kind: "AGG_TRADE", fidelity_mode: "AGG_TRADE_EXECUTION" };
  };
  const run = await runResearchBacktest({ api, request: precise, source });
  assert.equal(run.kind, "TERMINAL");
  assert.equal(run.frozenContext?.sourceKind, "IMPORTED_DATASET");
  assert.equal(run.frozenContext?.capabilitySummary.fidelityCeiling, "TRADE_TAPE");
  assert.deepEqual(calls, ["revision:PINE_ENGINE", "preview", "smoke", "validate", "preview", "create"]);

  await assert.rejects(runResearchBacktest({ api: importedApi([]), request: precise, source }),
    /frozen snapshot lacks the requested user market trades/);
});

test("continuous handoff sends its profile to preparation and never falls back to the default executor", async () => {
  const pythonBarExecution = { executionModel: "LEGACY", outputMode: "SIGNAL", warmupBars: 5 } as const;
  const chart = { ...request, language: "python" as const, pythonTrustedConfirmed: true,
    session: { ...request.session, interval: "1m" },
    attachment: { ...request.attachment, language: "python" as const, fidelityPreference: "FAST" as const, pythonBarExecution },
  };
  const calls: string[] = [];
  const api = apiWithResolutions([resolution("NEEDS_DATA")], calls);
  api.prepareChartContext = async (context, _signal, intent) => {
    assert.equal(context.interval, "1m");
    assert.deepEqual(intent?.python_bar_execution, pythonBarExecution);
    return { ...resolution(), prepared_run: completed() };
  };
  assert.equal((await runChartStrategyBacktest({ api, request: chart })).kind, "TERMINAL");
  const fallback = apiWithResolutions([resolution()], []);
  fallback.prepareChartContext = async () => { throw new Error("Unexpected preparation"); };
  await assert.rejects(runChartStrategyBacktest({ api: fallback, request: chart }), /profile was not prepared/);
});

test("Strategy Manager rejects a replay response for a different cursor or result hash", async () => {
  const cursor = { runId: "bt_replay", snapshotHash: "sha256:snapshot", reportHash: "sha256:report", cursor: 1, interval: "5m" };
  const good = {
    schema: "candlescope.user-trade-result-replay/1" as const, run_id: cursor.runId,
    snapshot_hash: cursor.snapshotHash, report_hash: cursor.reportHash, interval: cursor.interval,
    cursor: cursor.cursor, signal_interval: "1m", symbol: "ETH/USDC", quote_asset: "USDC",
    total: 20, time_ms: 1000, source_sequence: 200, bars: [], fills: [], order_events: [],
    order_trace_available: true, closed_bar_signals: [], signal_trace_available: true, fill_count: 0, cash: "10000", position: "0", equity: "10000",
  };
  let response: BacktestResultReplayFrame = good;
  const api: StrategyDataApi = {
    ...importedApi([]),
    async getReport() { return assert.fail("unexpected report load"); },
    async getChart() { return assert.fail("unexpected chart load"); },
    async cancelRun() { return assert.fail("unexpected cancellation"); },
    async listRuns() { return assert.fail("unexpected list"); },
    async compareRuns() { return assert.fail("unexpected comparison"); },
    async streamRun() { return assert.fail("unexpected stream"); },
    async getResultReplay() { return response; },
  };
  const manager = new StrategyDataManager(api);
  assert.deepEqual(await manager.loadResultReplay(cursor), good);
  const note = { id: "n", revision: 1, cursor: 1, time_ms: 1000, body: "Current print", saved_at_ms: 4000 };
  response = { ...good, notes: [note] };
  assert.deepEqual(await manager.loadResultReplay(cursor), response);
  response = { ...good, notes: [{ ...note, cursor: 2 }] };
  await assert.rejects(manager.loadResultReplay(cursor), /requested boundary/);
  response = { ...good, notes: [{ ...note, time_ms: 1001 }] };
  await assert.rejects(manager.loadResultReplay(cursor), /requested boundary/);
  response = { ...good, cursor: 2 };
  await assert.rejects(manager.loadResultReplay(cursor), /requested boundary/);
  response = { ...good, report_hash: "sha256:other" };
  await assert.rejects(manager.loadResultReplay(cursor), /requested boundary/);
  const linked = { ...cursor, comparisonInterval: "1m" };
  const bar = { open_time_ms: 900, close_time_ms: 1000, open: "1", high: "2", low: "1", close: "2", volume: "1", closed: true };
  response = { ...good, schema: "candlescope.local-bar-result-replay/1", comparison: { interval: "1m", bars: [bar] } };
  assert.deepEqual(await manager.loadResultReplay(linked), response);
  await assert.rejects(manager.loadResultReplay({ ...linked, comparisonInterval: "15m" }), /requested boundary/);
  response = { ...response, comparison: { interval: "1m", bars: [{ ...bar, close_time_ms: 1001 }] } };
  await assert.rejects(manager.loadResultReplay(linked), /requested boundary/);
  const withMa = { ...linked, comparisonMaPeriod: 2 };
  const ma = { period: 2, points: [{ open_time_ms: bar.open_time_ms, value: 1.5 }] };
  response = { ...response, comparison: { interval: "1m", bars: [bar], ma } };
  assert.deepEqual(await manager.loadResultReplay(withMa), response);
  await assert.rejects(manager.loadResultReplay({ ...withMa, comparisonMaPeriod: 3 }), /requested boundary/);
  response = { ...response, comparison: { interval: "1m", bars: [{ ...bar, closed: false }], ma } };
  await assert.rejects(manager.loadResultReplay(withMa), /requested boundary/);
  response = { ...response, comparison: { interval: "1m", bars: [bar], ma: {
    ...ma, points: [{ open_time_ms: 1001, value: 99 }],
  } } };
  await assert.rejects(manager.loadResultReplay(withMa), /requested boundary/);
  manager.dispose();
});

test("explicit market batch uses its own interval and sends the last included millisecond to preparation", async () => {
  const calls: string[] = [];
  const api = apiWithResolutions([resolution("NEEDS_DATA")], calls);
  const startMs = Date.UTC(2026, 0, 1);
  const endMs = startMs + 3_600_000;
  let observed = false;
  api.prepareChartContext = async (context, _signal, intent, key, progress) => {
    assert.equal(context.end_time_ms, endMs - 1);
    assert.equal(context.start_time_ms, startMs);
    assert.equal(context.interval, "1h");
    assert.equal(intent?.chart_cell_scope, request.cellScope);
    assert.match(key!, /^sha256:[a-f0-9]{64}$/);
    await progress?.({ id: "fixture" } as import("../../../data-preparation/api.js").PreparationJob);
    return { ...resolution(), prepared_run: completed() };
  };
  const outcome = await runResearchBacktest({
    api, request: { ...request, attachment: { ...request.attachment, rangeMode: "CUSTOM", customRange: { startMs, endMs } } },
    source: { kind: "MARKET_HISTORY", endTimeMsExclusive: endMs },
    onPreparation: () => { observed = true; },
  });
  assert.equal(outcome.kind, "TERMINAL");
  assert.equal(observed, true);
});

test("external models use the fixed BAR snapshot and pass smoke with the same parameters as the saved run", async () => {
  const calls: string[] = [];
  const externalRevision: StrategyRevisionRecord = {
    ...revision,
    revision_id: "external-revision",
    provider_kind: "EXTERNAL_PROVIDER",
    output_modes: ["TARGET_POSITION"],
    warmup_requirement: { bars: 3 },
    external_provider: {
      manifest_hash: "manifest",
      provider_id: "model",
      provider_revision: "v1",
      provider_kind: "MODEL",
      artifact_sha256: "artifact",
      runtime_lock: "runtime",
      reproducibility: "RECORDED_OUTPUT_ONLY",
    },
  };
  const connection = {
    connection_id: "external-connection",
    scope: {
      strategy_revision_id: externalRevision.revision_id,
      dataset_id: importedSource.datasetId,
      data_epoch: importedSource.dataEpoch,
      snapshot_hash: importedPreview().snapshot_hash,
      manifest_hash: externalRevision.external_provider!.manifest_hash,
    },
    scope_hash: "scope",
    connection_file: "/private/connection.json",
    ready: true,
    example_command: null,
  };
  const parameters = { quantity: "0.003" };
  const api = {
    ...importedApi(calls),
    externalProviders: {
      async list() { return [connection, { ...connection, scope: { ...connection.scope, data_epoch: "other" } }]; },
      async smoke(id: string, body: Record<string, unknown>, signal: AbortSignal) {
        calls.push("external-smoke");
        assert.ok(!signal.aborted);
        assert.equal(id, connection.connection_id);
        assert.equal(body.snapshot_hash, connection.scope.snapshot_hash);
        assert.equal(body.output_mode, "TARGET_POSITION");
        assert.deepEqual(body.parameters, parameters);
        return {};
      },
    },
    async validate(body: Record<string, unknown>) {
      calls.push("validate");
      assert.equal(body.external_connection_id, connection.connection_id);
      assert.deepEqual(body.parameters, parameters);
      return { ok: true };
    },
    async createRun(body: Record<string, unknown>, key: string) {
      calls.push("create");
      assert.ok(key);
      assert.equal(body.snapshot_hash, connection.scope.snapshot_hash);
      assert.equal(body.account_model, "SPOT_CASH_V1");
      assert.equal(body.warmup_bars, 3);
      assert.equal(body.strategy_draft_id, undefined);
      assert.deepEqual(body.parameters, parameters);
      return completed();
    },
  } as StrategyDataApi;
  const manager = new StrategyDataManager(api);
  const draft = await manager.prepareExternalModel({ source: importedSource, revision: externalRevision,
    settings: { rangeMode: "ALL_AVAILABLE", customRange: null }, outputMode: "TARGET_POSITION" });
  assert.deepEqual(await manager.externalModelConnections(draft), [connection]);
  await assert.rejects(manager.startExternalModel(draft, {
    ...connection, scope: { ...connection.scope, snapshot_hash: "other" },
  }, parameters), { code: "PROVIDER_CONNECTION_REQUIRED" });
  assert.deepEqual(calls, ["preview"]);
  await manager.startExternalModel(draft, connection, parameters);
  assert.deepEqual(calls, ["preview", "external-smoke", "validate", "create"]);
  manager.dispose();
});
