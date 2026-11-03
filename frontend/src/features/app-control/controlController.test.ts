import assert from "node:assert/strict";
import test from "node:test";
import { AppControlController, type ControlRuntimePort } from "./controlController.js";
import { indicatorSignature, type ControlCellObservation } from "./controlModel.js";
import { createDefaultChartWorkspaceRecord } from "../chart-workspace/chartWorkspaceLibrary.js";
import { applyControlWorkspaceCommand } from "../chart-workspace/chartWorkspaceControl.js";
import { visibleCellIds } from "../chart-workspace/chartWorkspaceLayout.js";

function fixture(waitMs = 80) {
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
  } }, "main-window", waitMs);
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

test("ready requires observations for the applied session and indicators plus completed persistence", async (t) => {
  t.mock.timers.enable({ apis: ["Date", "setTimeout"] });
  const f = fixture();
  f.observe(); // Old 1h session and empty indicator signature must not count.
  const staleOperation = f.controller.execute(f.request, () => {});
  t.mock.timers.tick(100);
  const result = await staleOperation;
  assert.equal(result.state, "applied"); assert.equal(result.code, "READINESS_TIMEOUT");
  const saved = fixture(200); saved.state.status.saveState = "saving";
  const operation = saved.controller.execute(saved.request, () => saved.observe());
  let settled = false;
  void operation.then(() => { settled = true; });
  t.mock.timers.tick(50);
  await Promise.resolve();
  assert.equal(settled, false, "ready must wait for persistence even when indicators are ready");
  saved.state.status.saveState = "saved";
  t.mock.timers.tick(50);
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

test("persistence failure, indicator failure and disposal cannot report ready", async (t) => {
  t.mock.timers.enable({ apis: ["Date", "setTimeout"] });
  const f = fixture(); f.state.status.saveState = "error"; f.state.status.error = "disk";
  assert.equal((await f.controller.execute(f.request, () => f.observe())).code, "PERSISTENCE_FAILED");
  const indicator = fixture();
  const indicatorOperation = indicator.controller.execute(indicator.request, () => indicator.observe({ indicatorsReady: false }));
  t.mock.timers.tick(100);
  assert.equal((await indicatorOperation).code, "READINESS_TIMEOUT");
  const disposed = fixture(); disposed.controller.dispose();
  assert.equal((await disposed.controller.execute(disposed.request, () => {})).code, "WINDOW_UNAVAILABLE");
});


test("restored default series metadata does not supersede an identical no-op configuration", async () => {
  const f = fixture();
  f.request.params.charts[0]!.indicators = [];
  const cell = f.state.view.document.cells[f.state.view.activeCellId]!;
  cell.session = { ...f.request.params.charts[0]!.session, providerId: "binance", venue: "binance",
    assetClass: "crypto", seriesVariant: "native", priceAdjustment: "raw",
    sessionVariant: "continuous", volumeSemantics: "base_asset" };
  cell.indicators = [];
  f.observe({ session: f.request.params.charts[0]!.session });
  assert.equal((await f.controller.execute(f.request, () => {})).state, "ready");
});

test("real session and series changes still supersede the pending target", async () => {
  for (const patch of [{ symbol: "ETHUSDT" }, { interval: "15m" }, { providerId: "alternate" },
    { venue: "alternate" }, { assetClass: "equity" }, { seriesVariant: "adjusted" },
    { priceAdjustment: "split" }, { sessionVariant: "regular" }, { volumeSemantics: "quote_asset" }]) {
    const f = fixture();
    const result = await f.controller.execute(f.request, () => {
      const cell = f.state.view.document.cells[f.state.view.activeCellId]!;
      cell.session = { ...cell.session, ...patch };
      f.observe();
    });
    assert.equal(result.code, "TARGET_CHANGED", JSON.stringify(patch));
  }
});

test("study and restoring observations reject live configuration before changing the workspace", async () => {
  for (const mode of ["history-study", "restoring-study"] as const) {
    const f = fixture(); f.observe({ mode });
    const before = JSON.stringify(f.state.view.document);
    assert.equal((await f.controller.execute(f.request, () => {})).code, "HISTORICAL_STUDY_ACTIVE");
    assert.equal(JSON.stringify(f.state.view.document), before);
    assert.equal(f.state.status.controlReceipt, null);
  }
});

test("entering study while a configuration awaits readiness cannot report the hidden live chart as ready", async () => {
  const f = fixture();
  const result = await f.controller.execute(f.request, () => f.observe({ mode: "history-study", barCount: 2 }));
  assert.equal(result.state, "applied");
  assert.equal(result.code, "HISTORICAL_STUDY_ACTIVE");
});

test("workspace diagnostics identify the visible study series independently of configured live input", () => {
  const f = fixture();
  const studySession = { exchange: "binance", marketType: "spot", symbol: "ETHUSDT", interval: "5m" };
  f.observe({ mode: "history-study", session: studySession, study: { id: "saved", cursorMs: 900_000, revision: 2 }, barCount: 2 });
  const snapshot = f.controller.inspect() as { cells: { session: unknown; configuredLiveSession: unknown; runtime: ControlCellObservation }[] };
  assert.deepEqual(snapshot.cells[0]!.session, studySession);
  assert.deepEqual(snapshot.cells[0]!.configuredLiveSession, f.state.view.activeCell.session);
  assert.equal(snapshot.cells[0]!.runtime.barCount, 2);
  assert.equal(snapshot.cells[0]!.runtime.study?.cursorMs, 900_000);
});
