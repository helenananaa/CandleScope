import assert from "node:assert/strict";
import test from "node:test";
import { ReplayChartResourcePool } from "../replayChartRuntimePool.js";
import { createReplayChartWorkspaceRepository, seedReplayChartWorkspace, seedForkReplayChartWorkspace } from "../replayChartWorkspaceRepository.js";
import { createDefaultChartWorkspaceRecord, createTemplateChartWorkspaceDocument } from "../../chart-workspace/chartWorkspaceLibrary.js";
import { visibleCellIds } from "../../chart-workspace/chartWorkspaceLayout.js";
import { createChartWorkspaceRepository } from "../../chart-workspace/chartWorkspaceRepository.js";
import { loadInitialChartSession } from "../../chart-session/chartSessionModel.js";
import { replayWorkspaceDrawingCharts } from "../useReplayWorkspaceDrawings.js";

test("forked drawing records are reparented without mutating the immutable parent", () => {
  const scope = "workspace:replay:parent:workspace-default:cell-1:binance:spot:BTCUSDT__main";
  const childScope = scope.replace("replay:parent:", "replay:child:");
  const parent = { documentSchemaVersion: 2, scopeKey: "replay-run:parent", charts: {
    [scope]: { documentSchemaVersion: 1, scopeKey: "replay-run:parent", documentRevision: 2, updatedAt: 1, entities: [] },
  } };
  const copied = replayWorkspaceDrawingCharts(parent, "child");
  assert.equal(copied[childScope]?.scopeKey, "replay-run:child");
  assert.equal(copied[childScope]?.documentRevision, 2);
  assert.equal(copied[scope], undefined);
  assert.equal(parent.charts[scope]?.scopeKey, "replay-run:parent");
  assert.equal(replayWorkspaceDrawingCharts(parent), parent.charts);
});

test("duplicate-period charts share a track and closing one does not release the remaining chart", async () => {
  const events: string[] = [];
  const pool = new ReplayChartResourcePool((id) => ({
    start: () => { events.push(`start:${id}`); },
    dispose: () => { events.push(`dispose:${id}`); },
  }));
  const source = pool.get("btc");
  const release1m = pool.retain("btc");
  const release15m = pool.retain("btc");
  assert.equal(source, pool.get("btc"));
  release1m();
  await Promise.resolve();
  assert.deepEqual(events, ["start:btc"]);
  const releaseEth = pool.retain("eth");
  release15m();
  await Promise.resolve();
  assert.deepEqual(events, ["start:btc", "start:eth", "dispose:btc"]);
  releaseEth();
  await Promise.resolve();
  assert.equal(events.at(-1), "dispose:eth");
});

test("StrictMode reacquisition cancels retirement and release is idempotent", async () => {
  let disposals = 0;
  const pool = new ReplayChartResourcePool(() => ({ start() {}, dispose() { disposals++; } }));
  const source = pool.get("btc");
  const release = pool.retain("btc");
  release();
  release();
  const nextRelease = pool.retain("btc");
  await Promise.resolve();
  assert.equal(pool.get("btc"), source);
  assert.equal(disposals, 0);
  nextRelease();
  await Promise.resolve();
  assert.equal(disposals, 1);
  assert.notEqual(pool.get("btc"), source);
});

test("replay workspace saves and recovers without reading or changing live/other-run layouts", async () => {
  const values = new Map<string, string>();
  const storage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
  };
  const live = createChartWorkspaceRepository({ indexedDB: null, storage });
  const liveBefore = await live.loadLibrary();
  liveBefore.workspaces[0]!.name = "Live layout must survive";
  await live.saveLibrary(liveBefore);
  const untouched = new Map(values);
  const session = loadInitialChartSession();
  const repository = createReplayChartWorkspaceRepository("run-a", session, storage);
  const loaded = await repository.loadLibrary();
  loaded.workspaces[0]!.name = "My replay";
  await repository.saveLibrary(loaded);
  for (const [key, value] of untouched) assert.equal(values.get(key), value);
  const recovered = await createReplayChartWorkspaceRepository("run-a", session, storage).loadLibrary();
  assert.equal(recovered.workspaces[0]!.name, "My replay");
  const other = await createReplayChartWorkspaceRepository("run-b", session, storage).loadLibrary();
  assert.notEqual(other.workspaces[0]!.name, "My replay");
  assert.deepEqual((await live.loadLibrary()).workspaces, liveBefore.workspaces);
});

test("new live-launched replay inherits four mixed charts and indicators without live computed values", async () => {
  const values = new Map<string,string>();
  const storage = { getItem:(key:string) => values.get(key) ?? null,
    setItem:(key:string,value:string) => { values.set(key,value); } };
  const source = createTemplateChartWorkspaceDocument("quad", createDefaultChartWorkspaceRecord().document);
  const ids = visibleCellIds(source.windows["main-window"]!.layoutTree);
  const types = ["renko","kagi","heikin-ashi","candlestick"] as const;
  for (const [index,id] of ids.entries()) {
    const cell = source.cells[id]!;
    cell.chartSettings.chartType = types[index]!;
    cell.session.symbol = "FUTURE-LIVE";
    cell.indicators = [{ id:"SMA",engineName:"SMA",params:{period:20},
      lines:[{data:[{time:9999999999,value:777}]}],renderHints:{future:777} }];
  }
  const before = JSON.stringify(source);
  assert.equal(seedReplayChartWorkspace("new-run", {document:source,windowId:"main-window"},storage),true);
  const session = {...loadInitialChartSession(),symbol:"TRAINING"};
  const repo = createReplayChartWorkspaceRepository("new-run",session,storage);
  const loaded = await repo.loadLibrary();
  const copied = loaded.workspaces[0]!.document;
  assert.equal(visibleCellIds(copied.windows["main-window"]!.layoutTree).length,4);
  assert.deepEqual(ids.map(id=>copied.cells[id]!.chartSettings.chartType),types);
  for (const id of ids) {
    const cell = copied.cells[id]!;
    assert.equal(cell.session.symbol,"TRAINING");
    assert.deepEqual(cell.indicators[0]!.params,{period:20});
    assert.deepEqual(cell.indicators[0]!.lines?.[0]!.data,[]);
    assert.equal(cell.indicators[0]!.renderHints,undefined);
    assert.equal(cell.strategyAttachment,null);
    assert.equal(cell.nativeStrategies,undefined);
  }
  assert.equal(JSON.stringify(source),before);
  copied.cells[ids[0]!]!.indicators = [];
  await repo.saveLibrary(loaded);
  seedReplayChartWorkspace("new-run", {document:source,windowId:"main-window"},storage);
  const resumed = await createReplayChartWorkspaceRepository("new-run",session,storage).loadLibrary();
  assert.deepEqual(resumed.workspaces[0]!.document.cells[ids[0]!]!.indicators,[]);
  const unrelated = await createReplayChartWorkspaceRepository("unrelated",session,storage).loadLibrary();
  assert.equal(visibleCellIds(unrelated.workspaces[0]!.document.windows["main-window"]!.layoutTree).length,1);
});

test("historical forks preserve mixed markets and layout while selected event owns the active interval", async () => {
  const values = new Map<string, string>();
  const storage = { getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); } };
  const source = createTemplateChartWorkspaceDocument("quad", createDefaultChartWorkspaceRecord().document);
  const window = source.windows["main-window"]!;
  const ids = visibleCellIds(window.layoutTree);
  const types = ["renko", "kagi", "point-and-figure", "candlestick"] as const;
  const symbols = ["BTCUSDT", "SOLUSDT", "SOLUSDT", "LATER-ADDED"];
  for (const [i, id] of ids.entries()) {
    const cell = source.cells[id]!;
    cell.session = { exchange: "binance", marketType: "futures", symbol: symbols[i]!, interval: i === 2 ? "7m" : "15m" };
    cell.chartSettings.chartType = types[i]!;
    cell.indicators = [{ id: "SMA", engineName: "SMA", params: { period: 10 },
      lines: [{ data: [{ time: 9999999999, value: 123 }] }] }];
  }
  window.activeCellId = ids[0]!;
  const parent = JSON.stringify(source);
  const fork = { tracks: ["BTCUSDT", "SOLUSDT"].map((symbol, i) => ({
    track_id: `track-${i + 1}`, exchange: "binance", market_type: "futures", symbol,
  })), viewer_state: { selected_track_id: "track-2", display_interval: "5m" } };
  assert.equal(seedForkReplayChartWorkspace("child", { document: source, windowId: window.id,
    workspaceId: "parent-workspace" }, fork, storage), true);
  const session = source.cells[ids[1]!]!.session;
  const repo = createReplayChartWorkspaceRepository("child", session, storage);
  const loaded = await repo.loadLibrary();
  const record = loaded.workspaces[0]!;
  assert.equal(record.id, "parent-workspace");
  const copied = record.document;
  assert.deepEqual(ids.map(id => copied.cells[id]!.session.symbol), ["BTCUSDT", "SOLUSDT", "SOLUSDT", "SOLUSDT"]);
  assert.deepEqual(ids.map(id => copied.cells[id]!.chartSettings.chartType), types);
  assert.equal(copied.windows["main-window"]!.activeCellId, ids[1]);
  assert.deepEqual(ids.map(id => copied.cells[id]!.session.interval), ["15m", "5m", "7m", "15m"]);
  for (const cell of Object.values(copied.cells)) assert.deepEqual(cell.indicators[0]!.lines?.[0]!.data, []);
  assert.equal(JSON.stringify(source), parent);
  copied.cells[ids[1]!]!.session.interval = "3m";
  await repo.saveLibrary(loaded);
  seedForkReplayChartWorkspace("child", { document: source, windowId: window.id }, fork, storage);
  const restored = await createReplayChartWorkspaceRepository("child", session, storage).loadLibrary();
  assert.equal(restored.workspaces[0]!.document.cells[ids[1]!]!.session.interval, "3m");
  assert.equal(seedForkReplayChartWorkspace("invalid", { document: source, windowId: window.id },
    { ...fork, viewer_state: { ...fork.viewer_state, selected_track_id: "missing" } }, storage), false);
  const hiddenEventMarket = { ...fork, tracks: [...fork.tracks,
    { track_id: "track-3", exchange: "binance", market_type: "futures", symbol: "ETHUSDT" }],
    viewer_state: { selected_track_id: "track-3", display_interval: "3m" } };
  // All visible markets may still be admitted, yet the old event's selected
  // market no longer has a chart in the current parent presentation.
  for (const id of ids) source.cells[id]!.session.symbol = "SOLUSDT";
  assert.equal(seedForkReplayChartWorkspace("hidden-event", { document: source, windowId: window.id }, hiddenEventMarket, storage), true);
  const hidden = await createReplayChartWorkspaceRepository("hidden-event", session, storage).loadLibrary();
  const hiddenDocument = hidden.workspaces[0]!.document;
  assert.equal(hiddenDocument.cells[window.activeCellId]!.session.symbol, "ETHUSDT");
  assert.equal(hiddenDocument.cells[window.activeCellId]!.session.interval, "3m");
  assert.equal(hiddenDocument.cells[ids[1]!]!.session.symbol, "SOLUSDT");
});
