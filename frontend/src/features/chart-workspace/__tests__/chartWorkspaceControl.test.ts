import assert from "node:assert/strict";
import test from "node:test";
import { createDefaultChartWorkspaceRecord } from "../chartWorkspaceLibrary.js";
import { applyControlWorkspaceCommand } from "../chartWorkspaceControl.js";
import { parseControlConfiguration } from "../../app-control/controlModel.js";
import { visibleCellIds } from "../chartWorkspaceLayout.js";

function request(revision: number) {
  return parseControlConfiguration({ requestId: "four-chart", workspaceId: "workspace-1", windowId: "main-window",
    expectedRevision: revision, layout: "quad", charts: ["5m", "15m", "1h", "4h"].map((interval) => ({
      session: { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval },
      indicators: [{ name: "EMA", period: 20 }, { name: "EMA", period: 60 }],
    })) });
}
test("four charts configure in one revision without modifying the input", () => {
  const original = createDefaultChartWorkspaceRecord(1).document;
  const before = structuredClone(original);
  const result = applyControlWorkspaceCommand(original, request(original.revision), { maxCellsPerWindow: 4 });
  assert.equal(result.document.revision, original.revision + 1);
  const ids = visibleCellIds(result.document.windows["main-window"]!.layoutTree);
  assert.equal(ids.length, 4);
  assert.deepEqual(ids.map((id) => result.document.cells[id]!.session.interval), ["5m", "15m", "1h", "4h"]);
  for (const id of ids) {
    assert.equal(result.document.cells[id]!.linkGroupId, null);
    assert.deepEqual(result.document.cells[id]!.indicators.map((item) => item.params?.period), [20, 60]);
  }
  assert.deepEqual(original, before);
});
test("stale revision, locked layout and capacity reject without partial effects", () => {
  const original = createDefaultChartWorkspaceRecord(1).document;
  assert.throws(() => applyControlWorkspaceCommand(original, request(original.revision + 1), {}), /REVISION_CONFLICT/);
  assert.throws(() => applyControlWorkspaceCommand(original, request(original.revision), { maxCellsPerWindow: 2 }), /LAYOUT_UNAVAILABLE/);
  const locked = structuredClone(original); locked.windows["main-window"]!.layoutLocked = true;
  assert.throws(() => applyControlWorkspaceCommand(locked, request(locked.revision), {}), /LAYOUT_LOCKED/);
  const bad = request(original.revision); bad.charts.pop();
  assert.throws(() => applyControlWorkspaceCommand(original, bad, {}), /CHART_COUNT_MISMATCH/);
});
test("control input rejects scripts, unknown keys, noncanonical intervals and out-of-budget indicators", () => {
  const raw = { requestId: "x", workspaceId: "w", windowId: "main-window", expectedRevision: 0,
    charts: [{ cellId: "cell-1", session: { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1h" }, indicators: [] as unknown[] }] };
  assert.throws(() => parseControlConfiguration({ ...raw, script: "bad" }), /Unknown/);
  raw.charts[0]!.indicators = [{ name: "EMA", period: 20, script: "bad" }];
  assert.throws(() => parseControlConfiguration(raw), /Unknown/);
  raw.charts[0]!.indicators = [{ name: "EMA", period: 5001 }];
  assert.throws(() => parseControlConfiguration(raw), /period/);
  raw.charts[0]!.indicators = [];
  raw.charts[0]!.session.interval = "60m";
  assert.throws(() => parseControlConfiguration(raw), /canonical/);
});
