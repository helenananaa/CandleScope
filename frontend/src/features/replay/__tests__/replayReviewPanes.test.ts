import assert from "node:assert/strict";
import test from "node:test";
import { createDrawingDocumentSessionRegistry } from "../../drawings/core/drawingDocumentStore.js";
import { importSavedDrawings } from "../../drawings/core/drawingCodec.js";
import { replayReviewDrawingRecord, replayReviewPaneDocuments } from "../replayReviewDrawing.js";
import { replayWorkspaceDrawingCharts, replayWorkspaceDrawingScopes } from "../useReplayWorkspaceDrawings.js";

const base = "workspace:replay:parent:workspace-a:cell-3:binance:futures:LTCUSDT";
const review = "replay-review:review-a:cell-3";
function line(scope: string, id: string) {
  return importSavedDrawings(scope, [{ type: "line", id, lineType: "line-segment",
    dataPoints: [{ time: 100, price: 10.25 }, { time: 200, price: 20.5 }], color: "#f59e0b", lineWidth: 2 }])!;
}
function fixture() {
  const main = line(`${base}__main`, "main-line");
  const rsi = line(`${base}__rsi-runtime-id`, "rsi-line");
  const other = line(`${base}:other-layer__rsi-runtime-id`, "unrelated");
  return { main, rsi, value: { documentSchemaVersion: 2, scopeKey: "replay-run:parent",
    charts: Object.fromEntries([main, rsi, other].map(document =>
      [document.scopeKey, replayReviewDrawingRecord(document, "parent", 123)])) } };
}

test("late pane editors notify scope subscribers once and join only their own replay cells", () => {
  const registry = createDrawingDocumentSessionRegistry();
  const revisions: number[] = [];
  const release = registry.subscribeScopeLoads(() => revisions.push(registry.getScopeRevision()));
  assert.deepEqual(replayWorkspaceDrawingScopes([base], registry.loadedScopes()), [`${base}__main`]);
  const f = fixture();
  for (const document of [f.main, f.rsi]) {
    const store = registry.getStore(document.scopeKey);
    store.loadDocument(document);
    registry.markLoaded(document.scopeKey, store);
    registry.markLoaded(document.scopeKey, store);
  }
  assert.deepEqual(revisions, [1, 2]);
  assert.deepEqual(replayWorkspaceDrawingScopes([base], [...registry.loadedScopes(), `${base}:other-layer__main`]),
    [f.main.scopeKey, f.rsi.scopeKey]);
  release();
  const extra = registry.getStore(`${base}__funding-rate`);
  registry.markLoaded(extra.getSnapshot().scopeKey, extra);
  assert.deepEqual(revisions, [1, 2]);
});

test("historical main and runtime-only pane records survive reparenting before indicator output loads", () => {
  const f = fixture();
  const before = JSON.stringify(f.value);
  const childBase = base.replace("replay:parent:", "replay:child:");
  const charts = replayWorkspaceDrawingCharts(f.value, "child");
  const scopes = replayWorkspaceDrawingScopes([childBase], Object.keys(charts));
  assert.deepEqual(scopes, [`${childBase}__main`, `${childBase}__rsi-runtime-id`]);
  const restored = replayReviewPaneDocuments({ ...f.value, charts }, childBase, review, []);
  assert.equal(restored.length, 2);
  assert.deepEqual([...restored[0]!.entities], [...f.main.entities]);
  assert.deepEqual([...restored[1]!.entities], [...f.rsi.entities]);
  assert.equal(JSON.stringify(f.value), before);
});

test("reviewing an earlier event clears future pane drawings without touching live or other-cell editors", () => {
  const f = fixture();
  const registry = createDrawingDocumentSessionRegistry();
  const live = registry.getStore(f.rsi.scopeKey); live.loadDocument(f.rsi);
  for (const document of replayReviewPaneDocuments(f.value, base, review, [])) {
    const store = registry.getStore(document.scopeKey); store.loadDocument(document); registry.markLoaded(document.scopeKey, store);
  }
  const unrelatedScope = `${review}:other-cell__rsi`;
  const other = registry.getStore(unrelatedScope); other.loadDocument(line(unrelatedScope, "other-line")); registry.markLoaded(unrelatedScope, other);
  const earlier = replayReviewPaneDocuments(null, base, review, registry.loadedScopes());
  assert.equal(earlier.length, 2);
  for (const document of earlier) registry.getStore(document.scopeKey).loadDocument(document);
  assert.equal(registry.getStore(`${review}__rsi-runtime-id`).getSnapshot().entities.size, 0);
  assert.equal(registry.getStore(`${review}__main`).getSnapshot().entities.size, 0);
  assert.equal(live.getSnapshot().entities.size, 1);
  assert.equal(other.getSnapshot().entities.size, 1);
  const legacy = replayReviewPaneDocuments(replayReviewDrawingRecord(f.main, "parent", 123), base, review, registry.loadedScopes());
  assert.equal(legacy.find(document => document.scopeKey.endsWith("__main"))!.entities.size, 1);
  assert.equal(legacy.find(document => document.scopeKey.endsWith("__rsi-runtime-id"))!.entities.size, 0);
});
