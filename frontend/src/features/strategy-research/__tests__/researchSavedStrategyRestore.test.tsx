import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { t } from "../../../i18n/index.js";
import type { BacktestSnapshot, StrategyRevisionRecord } from "../../backtest/backtestApi.js";
import PythonStudioPanel from "../../backtest/PythonStudioPanel.js";
import {
  PYTHON_STUDIO_STORAGE_KEY, persistPythonStudioState, pythonStudioPersisted, pythonStudioScope, restorePythonStudioState,
  restorePythonStudioStateFor, type PythonStudioGate,
} from "../../backtest/pythonStudio.js";
import { StrategyDataManager, type StrategyDataApi } from "../../market-data/manager/strategyDataManager.js";

const range = { datasetId: "local-a", dataEpoch: "epoch-a", interval: "1d", startTimeMs: 0, endTimeMs: 200 * 86_400_000 };
const identity = { bundle_id: "psb_1", bundle_hash: "sha256:b", manifest_hash: "sha256:m", source_hash: "sha256:s" };
const gate: PythonStudioGate = { revisionId: "srv2_bundle", bundleIdentity: identity, smokePassed: true, runtimeMode: "TRUSTED_LOCAL",
  trustedConfirmed: true, coverageReady: true, coverageReason: "", canCreateRun: true };

function memoryStorage() {
  const memory = new Map<string, string>();
  return { memory, getItem: (key: string) => memory.get(key) ?? null, setItem: (key: string, value: string) => { memory.set(key, value); },
    removeItem: (key: string) => { memory.delete(key); } };
}

test("a reload restores the frozen studio gate, and its smoke only on the data and range it passed on", () => {
  const storage = memoryStorage();
  const scope = pythonStudioScope(range);
  persistPythonStudioState(true, pythonStudioPersisted(gate, scope), storage);
  assert.deepEqual(restorePythonStudioStateFor(scope, storage), { revisionId: "srv2_bundle", runId: null, studyId: null, bundleId: "psb_1",
    bundleIdentity: identity, smokePassed: true, runtimeMode: "TRUSTED_LOCAL", trustedConfirmed: true, scope });
  for (const other of [{ datasetId: "local-b" }, { dataEpoch: "epoch-b" }, { interval: "4h" }, { startTimeMs: 86_400_000 },
    { endTimeMs: 100 * 86_400_000 }]) {
    const restored = restorePythonStudioStateFor(pythonStudioScope({ ...range, ...other }), storage);
    assert.equal(restored?.revisionId, "srv2_bundle", "the frozen revision is not tied to the data");
    assert.equal(restored?.smokePassed, false, `a smoke never carries to other data: ${JSON.stringify(other)}`);
  }
  const unscoped = memoryStorage();
  unscoped.setItem(PYTHON_STUDIO_STORAGE_KEY, JSON.stringify({ revisionId: "srv2_old", smokePassed: true }));
  assert.equal(restorePythonStudioStateFor(scope, unscoped)?.smokePassed, false, "a saved smoke without its data does not count");
  persistPythonStudioState(true, pythonStudioPersisted({ ...gate, revisionId: null }, scope), storage);
  assert.equal(restorePythonStudioStateFor(scope, storage), null, "nothing frozen, nothing to restore");
  assert.equal(restorePythonStudioState(true, memoryStorage()), null);
});

test("after a reload the studio opens ready to run its frozen revision; another revision or range needs a new smoke", () => {
  const storage = memoryStorage();
  persistPythonStudioState(true, pythonStudioPersisted({ ...gate, runtimeMode: "SANDBOXED_LOCAL", trustedConfirmed: false },
    pythonStudioScope(range)), storage);
  const snapshot = { snapshot_hash: "sha256:" + "a".repeat(64), row_count: 200 } as BacktestSnapshot;
  const render = (selectedRevisionId: string, endTimeMs = range.endTimeMs) => renderToStaticMarkup(<PythonStudioPanel api={{} as never}
    loading={false} snapshot={snapshot} datasetId={range.datasetId} startTimeMs={range.startTimeMs} endTimeMs={endTimeMs} schemaParameters={{}}
    selectedRevisionId={selectedRevisionId} restored={restorePythonStudioStateFor(pythonStudioScope({ ...range, endTimeMs }), storage)}
    trustedFlagEnabled={false} onLoading={() => undefined} onNotice={() => undefined} onError={() => undefined}
    onRevisionReady={() => undefined} onGateChange={() => undefined} />);
  const ready = render("srv2_bundle");
  assert.ok(ready.includes(t("backtest.smokeOk")), "no inspect, freeze or smoke again on the same data");
  assert.ok(ready.includes("sha256:b"), "the frozen bundle identity is shown again");
  assert.ok(render("srv2_other").includes(t("backtest.smokeRun")), "the smoke belongs to its revision");
  const otherRange = render("srv2_bundle", 100 * 86_400_000);
  assert.ok(otherRange.includes(t("backtest.smokeRun")), "the smoke belongs to its data and range");
  assert.ok(otherRange.includes("sha256:b"), "the frozen bundle still comes back on other data");
});

test("the workspace reloads the frozen revision by id through the strategy manager", async () => {
  const python = { revision_id: "srv2_bundle", provider_kind: "PYTHON_SOURCE" } as StrategyRevisionRecord;
  const calls: string[] = [];
  const manager = new StrategyDataManager({ async listStrategyRevisions() {
    calls.push("list");
    return [{ revision_id: "srv2_rsi", provider_kind: "BUILTIN_TEMPLATE" }, python];
  } } as unknown as StrategyDataApi);
  assert.equal(await manager.savedPythonRevision("srv2_bundle"), python);
  assert.equal(await manager.savedPythonRevision("srv2_rsi"), null, "only a Python bundle revision restores the studio");
  assert.equal(await manager.savedPythonRevision("srv2_gone"), null);
  assert.deepEqual(calls, ["list", "list", "list"]);
  await assert.rejects(new StrategyDataManager({} as StrategyDataApi).savedPythonRevision("srv2_bundle"), /unavailable/i);
  const workspace = readFileSync(new URL("../ResearchSavedStrategy.tsx", import.meta.url), "utf8");
  for (const token of ["persistPythonStudioState(", "restorePythonStudioState(", "restorePythonStudioStateFor(", "manager.savedPythonRevision(",
    "restored={restored}"]) {
    assert.ok(workspace.includes(token), token);
  }
  assert.doesNotMatch(workspace, /defaultBacktestApi/);
});
