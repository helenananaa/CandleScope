import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { StrategyRevisionRecord, ExternalProviderConnection } from "../../backtestApi.js";
import type { BacktestReport } from "../../backtestTypes.js";
import { structuralMock } from "../../../../test/testHelpers.js";
import { getLocale, setLocale } from "../../../../i18n/locale.js";
import type { BacktestResearchRuntime } from "../backtestResearchTypes.js";
import ResearchExternalProviderPanel from "../ResearchExternalProviderPanel.js";
import { editableResearchRunConfig, externalReportIsStale, externalRunDraft, externalSnapshotRequest, matchingExternalConnections } from "../externalProviderModel.js";

const revision: StrategyRevisionRecord = {
  revision_id: "srv_model", provider_kind: "EXTERNAL_PROVIDER", label: "External model", description: "",
  input_modes: ["BAR_CLOSE"], output_modes: ["TARGET_POSITION"], signal_clock: "BAR_CLOSE", required_features: ["close"],
  warmup_requirement: { kind: "FIXED_BARS", bars: 3 }, parameter_schema: [], accepts_source: false,
  external_provider: { manifest_hash: "sha256:manifest", provider_id: "model.example", provider_revision: "1", provider_kind: "MODEL",
    artifact_sha256: "sha256:artifact", runtime_lock: "python/test", reproducibility: "RECORDED_OUTPUT_ONLY" },
};
const config = { strategy_revision_id: "srv_model", dataset_id: "dataset_one", data_epoch: "epoch_one", snapshot_hash: "snapshot_one" };
const connection: ExternalProviderConnection = {
  connection_id: "epc_one", scope: { ...config, manifest_hash: "sha256:manifest" }, scope_hash: "sha256:scope",
  connection_file: "/private/connection.json", ready: true, example_command: "python -I -S -B example.py --connection /private/connection.json",
};

test("connections require the frozen model revision and complete selected data identity", () => {
  assert.deepEqual(matchingExternalConnections([connection], config, revision), [connection]);
  for (const field of ["strategy_revision_id", "dataset_id", "data_epoch", "snapshot_hash"] as const) {
    assert.deepEqual(matchingExternalConnections([{ ...connection, scope: { ...connection.scope, [field]: "different" } }], config, revision), []);
  }
  assert.deepEqual(matchingExternalConnections([{ ...connection, scope: { ...connection.scope, manifest_hash: "different" } }], config, revision), []);
});

test("switching to an external revision clears foreign model inputs and keeps Host execution settings", () => {
  const before = { strategy_revision_id: "srv_python", strategy_execution_revision: "python-source-v1", external_scope_hash: "old",
    external_provider_identity: {}, external_connection_id: "epc_old", parameters: { length: 24 }, strategy_source: "old source",
    python_runtime_mode: "TRUSTED_LOCAL", python_trusted_confirmed: true, warmup_bars: 0, output_mode: "SIGNAL", initial_balance: "4321" };
  const prepared = externalRunDraft(before, revision);
  assert.equal(prepared.initial_balance, "4321");
  assert.equal(prepared.warmup_bars, 3);
  assert.equal(prepared.output_mode, "TARGET_POSITION");
  assert.deepEqual(prepared.parameters, {});
  assert.equal(prepared.external_connection_id, undefined);
  assert.equal(prepared.python_runtime_mode, undefined);
  assert.equal(prepared.strategy_source, undefined);
  assert.equal(prepared.external_scope_hash, undefined);
  assert.equal(before.parameters.length, 24);
});

test("restored Run metadata is omitted from new requests while its connection and editable conditions remain", () => {
  const restored = { ...config, external_connection_id: "epc_one", external_scope_hash: "private-scope-hash",
    external_provider_identity: { model: "frozen" }, strategy_execution_revision: "external-decision-provider-v1", parameters: { quantity: "0.001" } };
  const editable = editableResearchRunConfig(restored);
  assert.equal(editable.external_connection_id, "epc_one");
  assert.deepEqual(editable.parameters, { quantity: "0.001" });
  assert.equal(editable.strategy_execution_revision, undefined);
  assert.equal(editable.external_provider_identity, undefined);
  assert.deepEqual(externalSnapshotRequest(editable), config);
});

test("an immutable external report becomes stale after model, data or parameter changes and can become current again", () => {
  const report = structuralMock<BacktestReport>({ identity: config, strategy: { external_provider: revision.external_provider } });
  const original = { parameters: { quantity: "0.001", nested: { a: 1, b: 2 } }, output_mode: "TARGET_POSITION", warmup_bars: 3 };
  const input = { report, run: structuralMock<NonNullable<BacktestResearchRuntime["view"]["activeRun"]>>({ config_json: JSON.stringify(original) }),
    revisionId: "srv_model", datasetId: "dataset_one", snapshot: { data_epoch: "epoch_one", snapshot_hash: "snapshot_one" }, draftText: JSON.stringify(original) };
  assert.equal(externalReportIsStale(input), false);
  assert.equal(externalReportIsStale({ ...input, report: { ...report, strategy: {} }, externalSelected: true, revisionId: "srv_other" }), true);
  assert.equal(externalReportIsStale({ ...input, revisionId: "srv_other" }), true);
  assert.equal(externalReportIsStale({ ...input, snapshot: { ...input.snapshot, data_epoch: "new_epoch" } }), true);
  assert.equal(externalReportIsStale({ ...input, draftText: JSON.stringify({ ...original, parameters: { quantity: "0.002" } }) }), true);
  assert.equal(externalReportIsStale({ ...input, draftText: JSON.stringify({ ...original, parameters: { nested: { b: 2, a: 1 }, quantity: "0.001" } }) }), false);
  assert.equal(externalReportIsStale(input), false);
});

test("disabled model controls expose no launch action; an enabled matching connection shows its private-file command and status", () => {
  const previous = getLocale();
  setLocale("en");
  try {
    const runtime = structuralMock<BacktestResearchRuntime>({ view: { capabilities: { flags: { BACKTEST_EXTERNAL_PROVIDER_ENABLED: false } },
      revisions: [revision], selectedRevisionId: revision.revision_id, datasets: [], selectedDatasetId: "dataset_one",
      snapshot: null, externalConnections: [connection], externalConnection: connection, busy: false } });
    const disabled = renderToStaticMarkup(<ResearchExternalProviderPanel runtime={runtime} />);
    assert.match(disabled, /not enabled/);
    assert.doesNotMatch(disabled, /Create connection|example.py/);
    runtime.view.capabilities!.flags.BACKTEST_EXTERNAL_PROVIDER_ENABLED = true;
    const enabled = renderToStaticMarkup(<ResearchExternalProviderPanel runtime={runtime} />);
    assert.match(enabled, /External client connected/);
    assert.match(enabled, /example.py/);
    assert.doesNotMatch(enabled, /Bearer|token/);
  } finally { setLocale(previous); }
});

test("report freshness follows the submitted account, cost, sizing, clock and risk settings", () => {
  const original = { ...config, parameters: {}, warmup_bars: 3, output_mode: "TARGET_POSITION",
    account_model: "SPOT_CASH_V1", initial_balance: "10000", slippage_bps: "1", taker_fee_bps: "0",
    fixed_qty: "0.001", latency_events: 0, max_drawdown_percent: "50" };
  const input = { report: structuralMock<BacktestReport>({ identity: config, strategy: { external_provider: revision.external_provider } }),
    run: structuralMock<NonNullable<BacktestResearchRuntime["view"]["activeRun"]>>({ config_json: JSON.stringify(original) }),
    revisionId: "srv_model", datasetId: "dataset_one", snapshot: { data_epoch: "epoch_one", snapshot_hash: "snapshot_one" },
    draftText: JSON.stringify(original), request: original };
  assert.equal(externalReportIsStale(input), false);
  for (const changed of [{ account_model: "LINEAR_PERP_ONE_WAY_V1" }, { initial_balance: "4321" },
    { slippage_bps: "2" }, { taker_fee_bps: "1" }, { fixed_qty: "0.002" }, { latency_events: 1 }, { max_drawdown_percent: "10" }]) {
    assert.equal(externalReportIsStale({ ...input, request: { ...original, ...changed } }), true);
  }
  assert.equal(externalReportIsStale({ ...input, request: { ...original, external_connection_id: "new_connection" } }), false);
  assert.equal(externalReportIsStale({ ...input, request: null }), true);
  assert.equal(externalReportIsStale({ ...input, request: undefined, draftText: "{" }), true);
  assert.equal(externalReportIsStale(input), false);
});
