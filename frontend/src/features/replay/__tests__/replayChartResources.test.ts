import assert from "node:assert/strict";
import test from "node:test";
import { ReplayChartResourcePool } from "../replayChartRuntimePool.js";
import { createReplayChartWorkspaceRepository } from "../replayChartWorkspaceRepository.js";
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
