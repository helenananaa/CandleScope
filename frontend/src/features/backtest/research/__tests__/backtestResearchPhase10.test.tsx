import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { createBacktestApi } from "../../backtestApi.js";
import type { BacktestDataset, BacktestSnapshot } from "../../backtestApi.js";
import type {
  BacktestChartData,
  BacktestReport,
  BacktestResearchLaunchContext,
  BacktestRunRecord,
} from "../../backtestTypes.js";
import type { ChartStrategyResultBundle } from "../../chart-tester/chartStrategyResultCache.js";
import {
  backtestResearchHasPanel,
  backtestResearchPanels,
  researchFrozenSnapshotIdentity,
  researchReturnHref,
  researchRunIdentityReady,
  researchSessionFromAuthority,
  shouldEnableBacktestResearchLiveSource,
} from "../backtestResearchModel.js";
import {
  backtestResearchContextHref,
  buildBacktestResearchLaunchContext,
} from "../backtestResearchLaunch.js";
import ResearchTaskPicker from "../ResearchTaskPicker.js";

const context: BacktestResearchLaunchContext = {
  schema_version: "candlescope.backtest-research-launch-context/1",
  context_id: "brc_context_12345678",
  context_hash: "sha256:context",
  source_workspace_id: "workspace-main",
  source_cell_id: "cell-main",
  strategy_draft_id: "draft-12345678",
  strategy_revision_id: "rev-12345678",
  parameters: { fast: 3 },
  quick_preset_id: "crypto-perp-conservative-v1",
  chart_session: {
    exchange: "okx",
    market_type: "swap",
    symbol: "ETHUSDT",
    interval: "1h",
  },
  range: { mode: "CUSTOM", start_time_ms: 1000, end_time_ms: 2000 },
  dataset_identity: {
    dataset_id: "dataset-12345678",
    data_epoch: "sha256:epoch",
    snapshot_hash: "sha256:snapshot",
  },
  latest_run_id: "bt_result_12345678",
  baseline_run_id: "bt_baseline_12345678",
  created_at_ms: 1,
};

test("five research tasks expose only their declared shared panel composition", () => {
  assert.deepEqual(backtestResearchPanels("PRECISE_EXECUTION"), [
    "STRATEGY", "DATA", "EXECUTION", "RUN", "RESULTS",
  ]);
  assert.equal(backtestResearchHasPanel("PARAMETER_ROBUSTNESS", "STUDY"), true);
  assert.equal(backtestResearchHasPanel("PARAMETER_ROBUSTNESS", "EXECUTION"), false);
  assert.equal(backtestResearchHasPanel("PYTHON_MODEL", "DATA"), false);
  assert.deepEqual(backtestResearchPanels("REPLAY_REVIEW"), ["RUN", "REPLAY", "RESULTS"]);
});

test("task home renders five functional task entries without mounting a chart", () => {
  const html = renderToStaticMarkup(
    <ResearchTaskPicker returnHref="/" onSelect={() => undefined} />,
  );
  assert.equal((html.match(/data-research-task=/g) ?? []).length, 5);
  assert.match(html, /research-task-home/);
  assert.doesNotMatch(html, /chart-area/);
});

test("authority restores context session and safely returns to a scoped chart", () => {
  assert.deepEqual(researchSessionFromAuthority({ context, run: null, chart: null }), {
    exchange: "okx",
    marketType: "swap",
    symbol: "ETHUSDT",
    interval: "1h",
  });
  assert.equal(
    researchReturnHref(context),
    "/?workspace=workspace-main&cell=cell-main&source=backtest-research",
  );
  assert.equal(researchReturnHref({ ...context, source_cell_id: null }), "/");
  assert.equal(
    researchReturnHref({ ...context, source_workspace_id: "strategy-research", source_cell_id: "imported" }),
    "/strategy.html?source=imported",
  );
  assert.equal(
    researchReturnHref({ ...context, source_workspace_id: "strategy-research", source_cell_id: "current" }),
    "/strategy.html",
  );
});

test("Run deep link derives session from immutable Run config and chart", () => {
  const run: BacktestRunRecord = {
    run_id: "bt_result_12345678",
    state: "COMPLETED",
    fidelity_mode: "BAR_APPROX",
    source_event_kind: "BAR",
    config_hash: "sha256:config",
    config_json: JSON.stringify({ exchange: "binance", market_type: "usdm", symbol: "BTCUSDT", interval: "15m" }),
  };
  assert.deepEqual(researchSessionFromAuthority({
    context: null,
    run,
    chart: { run_id: run.run_id, chart_hash: "sha256:chart", symbol: "SOLUSDT", interval: "5m", bars: [], fills: [], equity_curve: [], truncated: false },
  }), { exchange: "binance", marketType: "usdm", symbol: "SOLUSDT", interval: "5m" });
  assert.equal(researchRunIdentityReady({
    run,
    report: null,
    chart: null,
  }), false);
});

test("a queued non-BTC Run keeps its matching frozen context identity before its chart arrives", () => {
  const run: BacktestRunRecord = { run_id: "bt_queued", dataset_id: context.dataset_identity!.dataset_id,
    data_epoch: context.dataset_identity!.data_epoch, state: "QUEUED", fidelity_mode: "BAR_APPROX", source_event_kind: "BAR",
    config_hash: "sha256:queued", config_json: JSON.stringify({ exchange: "okx", market_type: "swap", interval: "1h" }) };
  assert.equal(researchSessionFromAuthority({ context, run, chart: null }).symbol, "ETHUSDT");
  assert.notEqual(researchSessionFromAuthority({ context, run: { ...run, data_epoch: "other_epoch" }, chart: null }).symbol, "ETHUSDT");
  const chart = { run_id: run.run_id, chart_hash: "sha256:chart", symbol: "LTCUSDT", interval: "1m", bars: [], fills: [], equity_curve: [], truncated: false };
  assert.equal(researchSessionFromAuthority({ context, run: { ...run, state: "COMPLETED" }, chart }).symbol, "LTCUSDT");
});

test("an imported launch without a quick-test snapshot binds a queued Run through its exact dataset epoch", () => {
  const run: BacktestRunRecord = { run_id: "bt_imported_queued", dataset_id: "local_ltc", data_epoch: "epoch_ltc",
    state: "QUEUED", fidelity_mode: "BAR_APPROX", source_event_kind: "BAR", config_hash: "sha256:queued",
    config_json: JSON.stringify({ exchange: "local", market_type: "spot", interval: "1m" }) };
  const dataset: BacktestDataset = { dataset_id: "local_ltc", data_epoch: "epoch_ltc", symbol: "LTCUSDT", interval: "1m",
    name: "imported LTC", rows: 8, first_open_ms: 0, last_close_ms: 479999, strategy_revisions: [] };
  const input = { context: { ...context, dataset_identity: null }, run, chart: null, dataset };
  assert.equal(researchSessionFromAuthority(input).symbol, "LTCUSDT");
  assert.notEqual(researchSessionFromAuthority({ ...input, dataset: { ...dataset, data_epoch: "changed_epoch" } }).symbol, "LTCUSDT");
  assert.notEqual(researchSessionFromAuthority({ ...input, dataset: { ...dataset, dataset_id: "different_dataset" } }).symbol, "LTCUSDT");
});

test("a legacy queued trade Run uses its verified snapshot rather than a different BAR catalog epoch", () => {
  const run: BacktestRunRecord = { run_id: "bt_trade_queued", dataset_id: "local_ltc", data_epoch: "trade_epoch",
    snapshot_hash: "trade_hash", state: "QUEUED", fidelity_mode: "AGG_TRADE_EXECUTION", source_event_kind: "AGG_TRADE",
    config_hash: "sha256:queued", config_json: JSON.stringify({ exchange: "binance", market_type: "futures", interval: "1m", symbol: null }) };
  const dataset: BacktestDataset = { dataset_id: "local_ltc", data_epoch: "bar_epoch", symbol: "LTCUSDT", interval: "1m",
    name: "original imported BARs", rows: 6, first_open_ms: 0, last_close_ms: 359999, strategy_revisions: [] };
  const tradeSnapshot: BacktestSnapshot = { data_epoch: "trade_epoch", snapshot_hash: "trade_hash",
    coverage_start_ms: 0, coverage_end_ms: 359999, row_count: 355, quality: {}, fidelity_capabilities: ["AGG_TRADE_EXECUTION"],
    catalog_dataset_id: "local_ltc", identity: { symbol: "LTCUSDT" } };
  const input = { context: null, run, chart: null, dataset, snapshot: tradeSnapshot };
  assert.equal(researchSessionFromAuthority(input).symbol, "LTCUSDT");
  assert.equal(researchSessionFromAuthority({ ...input, run: { ...run, config_json: JSON.stringify({ symbol: "WRONGUSDT" }) } }).symbol, "LTCUSDT");
  for (const changed of [{ data_epoch: "different_epoch" }, { snapshot_hash: "different_hash" },
    { catalog_dataset_id: "different_dataset" }, { identity: { symbol: 42 } }]) {
    assert.notEqual(researchSessionFromAuthority({ ...input, snapshot: { ...tradeSnapshot, ...changed } }).symbol, "LTCUSDT");
  }
});

test("selected Run overrides a launch context from another chart", () => {
  const run: BacktestRunRecord = {
    run_id: "bt_result_btc_12345678",
    state: "COMPLETED",
    fidelity_mode: "BAR_APPROX",
    source_event_kind: "BAR",
    config_hash: "sha256:config",
    config_json: JSON.stringify({
      exchange: "binance",
      market_type: "usdm",
      symbol: "BTCUSDT",
      interval: "15m",
    }),
  };
  assert.deepEqual(researchSessionFromAuthority({
    context,
    run,
    chart: {
      run_id: run.run_id,
      chart_hash: "sha256:chart",
      symbol: "BTCUSDT",
      interval: "15m",
      bars: [],
      fills: [],
      equity_curve: [],
      truncated: false,
    },
  }), { exchange: "binance", marketType: "usdm", symbol: "BTCUSDT", interval: "15m" });
});

test("frozen snapshot accepts bars only when dataset, snapshot, Run, and chart identities agree", () => {
  const dataset = {
    dataset_id: "dataset-btc",
    data_epoch: "sha256:epoch",
    name: "BTC",
    symbol: "BTCUSDT",
    interval: "15m",
    rows: 10,
    first_open_ms: 1,
    last_close_ms: 2,
    strategy_revisions: [],
  } satisfies BacktestDataset;
  const snapshot = {
    data_epoch: dataset.data_epoch,
    snapshot_hash: "sha256:snapshot",
    coverage_start_ms: 1,
    coverage_end_ms: 2,
    row_count: 10,
    quality: {},
    fidelity_capabilities: ["BAR_APPROX"],
  } satisfies BacktestSnapshot;
  const run: BacktestRunRecord = {
    run_id: "bt_result_12345678",
    state: "COMPLETED",
    fidelity_mode: "BAR_APPROX",
    source_event_kind: "BAR",
    config_hash: "sha256:config",
    dataset_id: dataset.dataset_id,
    data_epoch: snapshot.data_epoch,
    snapshot_hash: snapshot.snapshot_hash,
  };
  const report = {
    hashes: { report: "sha256:report" },
  } as unknown as BacktestReport;
  const chart = {
    run_id: run.run_id,
    chart_hash: "sha256:chart",
    symbol: dataset.symbol,
    interval: dataset.interval,
    bars: [],
    fills: [],
    equity_curve: [],
    truncated: false,
  } satisfies BacktestChartData;
  assert.deepEqual(researchFrozenSnapshotIdentity({ dataset, snapshot, run, report, chart }), {
    dataset_id: dataset.dataset_id,
    data_epoch: snapshot.data_epoch,
    snapshot_hash: snapshot.snapshot_hash,
  });
  assert.equal(researchFrozenSnapshotIdentity({
    dataset: { ...dataset, dataset_id: "dataset-eth" }, snapshot, run, report, chart,
  }), null);
  assert.equal(researchFrozenSnapshotIdentity({
    dataset, snapshot: { ...snapshot, snapshot_hash: "sha256:other" }, run, report, chart,
  }), null);
  assert.equal(researchFrozenSnapshotIdentity({
    dataset, snapshot, run, report, chart: { ...chart, symbol: "ETHUSDT" },
  }), null);
});

test("live market transport is disabled for offline and immutable sources", () => {
  assert.equal(shouldEnableBacktestResearchLiveSource("LIVE", "LIVE_REFERENCE"), true);
  assert.equal(shouldEnableBacktestResearchLiveSource("LOCAL_OFFLINE", "LIVE_REFERENCE"), false);
  assert.equal(shouldEnableBacktestResearchLiveSource("LIVE", "RUN_RESULT"), false);
  assert.equal(shouldEnableBacktestResearchLiveSource(null, "FROZEN_SNAPSHOT"), false);
});

test("quick tester launch context carries IDs and frozen selection without source copies", () => {
  const result = {
    run: {
      run_id: "bt_result_12345678",
      state: "COMPLETED",
      fidelity_mode: "BAR_APPROX",
      source_event_kind: "BAR",
      config_hash: "sha256:config",
      dataset_id: "dataset-12345678",
      data_epoch: "sha256:epoch",
      snapshot_hash: "sha256:snapshot",
    },
    config: { start_time_ms: 1000, end_time_ms: 2000 },
  } as ChartStrategyResultBundle;
  const payload = buildBacktestResearchLaunchContext({
    workspaceId: "workspace-main",
    cellId: "cell-main",
    session: { exchange: "binance", marketType: "usdm", symbol: "BTCUSDT", interval: "15m" },
    attachment: {
      schemaVersion: 1,
      strategyDraftId: "draft-12345678",
      strategyRevisionId: "rev-12345678",
      displayName: "SMA",
      language: "pyne",
      parameters: { fast: 3 },
      rangeMode: "CUSTOM",
      customRange: { startMs: 10, endMs: 20 },
      fidelityPreference: "FAST",
      quickPresetId: "crypto-perp-conservative-v1",
      autoRun: true,
    },
    result,
    resolution: null,
    activeRunId: result.run.run_id,
    baselineRunId: "bt_baseline_12345678",
    entryTask: "PARAMETER_ROBUSTNESS",
  });
  assert.equal(payload.latest_run_id, result.run.run_id);
  assert.deepEqual(payload.range, { mode: "CUSTOM", start_time_ms: 10, end_time_ms: 20 });
  assert.equal("source" in payload, false);
  assert.equal(payload.entry_task, "PARAMETER_ROBUSTNESS");
  assert.equal(backtestResearchContextHref("brc_context_12345678"), "/backtest.html?context=brc_context_12345678");
});

test("research context API posts payload and re-reads by opaque ID", async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ url: string; method: string }> = [];
  globalThis.fetch = (async (input, init) => {
    const url = String(input);
    calls.push({ url, method: String(init?.method ?? "GET") });
    return new Response(JSON.stringify(context), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;
  try {
    const api = createBacktestApi("/api/v1/backtests");
    const input = {
      source_workspace_id: context.source_workspace_id,
      source_cell_id: context.source_cell_id,
      strategy_draft_id: context.strategy_draft_id,
      strategy_revision_id: context.strategy_revision_id,
      parameters: context.parameters,
      quick_preset_id: context.quick_preset_id,
      chart_session: context.chart_session,
      range: context.range,
      dataset_identity: context.dataset_identity,
      latest_run_id: context.latest_run_id,
      baseline_run_id: context.baseline_run_id,
      entry_task: "PARAMETER_ROBUSTNESS" as const,
    };
    await api.createResearchLaunchContext(input);
    await api.getResearchLaunchContext(context.context_id);
    assert.deepEqual(calls, [
      { url: "/api/v1/backtests/research/contexts", method: "POST" },
      { url: "/api/v1/backtests/research/contexts/brc_context_12345678", method: "GET" },
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
