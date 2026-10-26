import assert from "node:assert/strict";
import test from "node:test";
import { AppControlController, type ControlRuntimePort } from "./controlController.js";
import { indicatorSignature, type ControlCellObservation } from "./controlModel.js";
import { createDefaultChartWorkspaceRecord } from "../chart-workspace/chartWorkspaceLibrary.js";
import { applyControlWorkspaceCommand } from "../chart-workspace/chartWorkspaceControl.js";
import { visibleCellIds } from "../chart-workspace/chartWorkspaceLayout.js";

function fixture() {
  const record = createDefaultChartWorkspaceRecord(1);
  const document = record.document;
  const window = document.windows["main-window"]!;
  const ids = visibleCellIds(window.layoutTree);
  const state: ReturnType<ControlRuntimePort["read"]> = {
    view: { document, window, activeWorkspaceId: record.id, activeWorkspaceName: record.name,
      runtimeKey: "test", workspaces: [], layout: "single", activeCellId: ids[0]!, activeCell: document.cells[ids[0]!]!,
      layoutCellIds: ids, visibleCellIds: ids, maxCellsPerWindow: 4, multiChart16Enabled: false,
      layoutLocked: false, canUndoLayout: false, canRedoLayout: false, ready: true },
    status: { controlReceipt: null, saveState: "saved", persistenceMode: "indexeddb", lastSavedAt: 1, error: null },
  };
  const controller = new AppControlController({ read: () => state, apply: (command) => {
    const result = applyControlWorkspaceCommand(state.view.document, command, { maxCellsPerWindow: 4 });
    state.view.document = result.document;
    state.view.layoutCellIds = visibleCellIds(result.document.windows["main-window"]!.layoutTree);
    state.status.controlReceipt = { requestId: command.requestId, ok: true, revision: result.document.revision,
      cellIds: state.view.layoutCellIds };
  } }, "main-window", 80);
  const request = { id: "edit", method: "workspace.configure", params: { requestId: "edit", workspaceId: record.id,
    windowId: "main-window", expectedRevision: document.revision, layout: "single", charts: [{
      session: { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "5m" }, indicators: [{ name: "EMA", period: 20 }],
    }] } };
  const observe = (patch: Partial<ControlCellObservation> = {}) => {
    const cell = state.view.document.cells[ids[0]!]!;
    controller.reportCell(ids[0]!, { session: cell.session, indicatorSignature: indicatorSignature(cell.indicators),
      marketReady: true, indicatorsReady: true, barCount: 500, loading: false, initialHistoryPending: false,
      loadingMoreLeft: false, paused: false, computing: false, indicatorErrors: [], indicatorOutputPoints: [500], error: null, ...patch });
  };
  return { state, controller, request, observe };
}

test("ready requires observations for the applied session and indicators plus completed persistence", async () => {
  const f = fixture();
  f.observe(); // Old 1h session and empty indicator signature must not count.
  const result = await f.controller.execute(f.request, () => {});
  assert.equal(result.state, "applied"); assert.equal(result.code, "READINESS_TIMEOUT");
  const saved = fixture(); saved.state.status.saveState = "saving";
  const operation = saved.controller.execute(saved.request, () => saved.observe());
  setTimeout(() => { saved.state.status.saveState = "saved"; }, 10);
  assert.equal((await operation).state, "ready");
});

test("viewport revisions do not supersede configuration, but an altered target does even after the receipt disappears", async () => {
  const f = fixture();
  const result = await f.controller.execute(f.request, () => {
    f.state.view.document = { ...f.state.view.document, revision: f.state.view.document.revision + 1 };
    f.observe();
  });
  assert.equal(result.state, "ready");
  const changed = fixture();
  const rejected = await changed.controller.execute(changed.request, () => {
    changed.state.status.controlReceipt = null;
    changed.state.view.activeWorkspaceId = "another-workspace";
    changed.observe();
  });
  assert.equal(rejected.code, "TARGET_CHANGED"); assert.equal(rejected.state, "applied");
});

test("persistence failure, indicator failure and disposal cannot report ready", async () => {
  const f = fixture(); f.state.status.saveState = "error"; f.state.status.error = "disk";
  assert.equal((await f.controller.execute(f.request, () => f.observe())).code, "PERSISTENCE_FAILED");
  const indicator = fixture();
  assert.equal((await indicator.controller.execute(indicator.request, () => indicator.observe({ indicatorsReady: false }))).code, "READINESS_TIMEOUT");
  const disposed = fixture(); disposed.controller.dispose();
  assert.equal((await disposed.controller.execute(disposed.request, () => {})).code, "WINDOW_UNAVAILABLE");
});
