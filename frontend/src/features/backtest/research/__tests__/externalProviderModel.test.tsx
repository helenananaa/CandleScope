import assert from "node:assert/strict";
import test from "node:test";
import type { StrategyRevisionRecord, ExternalProviderConnection } from "../../backtestApi.js";
import { externalSnapshotRequest, matchingExternalConnections } from "../externalProviderModel.js";

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

test("a connection's snapshot request names exactly the run's frozen identity", () => {
  const restored = { ...config, external_connection_id: "epc_one", parameters: { quantity: "0.001" }, taker_fee_bps: "4" };
  assert.deepEqual(externalSnapshotRequest(restored), config);
  assert.deepEqual(matchingExternalConnections([connection], config, { ...revision, provider_kind: "PYTHON_SOURCE" }), [],
    "only an external model revision has connections");
});
