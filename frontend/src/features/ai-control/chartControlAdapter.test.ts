import assert from "node:assert/strict";
import test from "node:test";
import { ChartControlAdapter } from "./chartControlAdapter.js";
import { createDefaultChartWorkspace } from "../chart-workspace/chartWorkspaceStorage.js";
import type { ChartWorkspaceRuntime } from "../chart-workspace/useChartWorkspaceRuntime.js";
import type { AiControlBridge, AiControlRequest } from "./aiControlTypes.js";
import { partialMock } from "../../test/testHelpers.js";

function fixture() {
  let document = createDefaultChartWorkspace();
  let candidate = document;
  const replies: Parameters<AiControlBridge["aiControlReply"]>[0][] = [];
  const publications: Parameters<AiControlBridge["aiControlPublish"]>[0][] = [];
  const adapter = new ChartControlAdapter({ aiControlPublish: async (views) => { publications.push(views); return { ok: true }; }, aiControlReply: (reply) => { replies.push(reply); } });
  const runtime = (key = "workspace-1") => partialMock<ChartWorkspaceRuntime>({
    view: partialMock<ChartWorkspaceRuntime["view"]>({ document, ready: true, runtimeKey: key, activeCellId: "cell-1", layoutCellIds: ["cell-1", "cell-2"] }),
    actions: partialMock<ChartWorkspaceRuntime["actions"]>({
      updateCellSession: (id, session) => { candidate = { ...candidate, cells: { ...candidate.cells, [id]: { ...candidate.cells[id]!, session } }, revision: candidate.revision + 1 }; },
      updateCellChartSettings: (id, chartSettings) => { candidate = { ...candidate, cells: { ...candidate.cells, [id]: { ...candidate.cells[id]!, chartSettings } }, revision: candidate.revision + 1 }; },
    }),
  });
  adapter.update(runtime(), "window-1", "market");
  const request = (patch: Partial<NonNullable<AiControlRequest["arguments"]>> = {}): AiControlRequest => ({
    type: "request", requestId: crypto.randomUUID(), name: "candlescope_set_chart",
    arguments: { windowId: "window-1", viewId: "cell-2", expectedRevision: adapter.views()[0]!.revision, operationId: "op-1", interval: "5m", ...patch },
  });
  return { adapter, replies, publications, runtime, request, commit() { document = candidate; adapter.update(runtime(), "window-1", "market"); } };
}

test("targeted change waits for committed render and returns observed configuration", async () => {
  const f = fixture(); const request = f.request({ chartType: "renko" });
  const task = f.adapter.handle(request); await Promise.resolve();
  assert.equal(f.replies.length, 0);
  f.commit(); await task;
  const reply = f.replies[0]!; assert.equal(reply.ok, true);
  assert.deepEqual(reply.result?.affectedViews, ["cell-2"]);
  const view = reply.result?.view as Record<string, unknown>;
  assert.equal(view.viewId, "cell-2"); assert.equal(view.active, false); assert.equal(view.chartType, "renko");
  assert.equal((view.session as Record<string, unknown>).interval, "5m");
  assert.notEqual(view.revision, request.arguments!.expectedRevision);
  assert.equal(f.runtime().view.activeCellId, "cell-1");
});

test("wrong target, stale revision, unsupported chart and unsupported calendar interval never mutate", async () => {
  const f = fixture(); const before = f.runtime().view.document;
  for (const [patch, code] of [
    [{ windowId: "wrong" }, "CONTROL_WINDOW_MISMATCH"], [{ viewId: "cell-4" }, "CONTROL_VIEW_NOT_FOUND"],
    [{ expectedRevision: "old" }, "CONTROL_REVISION_CONFLICT"], [{ chartType: "not-real" }, "INVALID_CHART_TYPE"],
    [{ interval: "12001M" }, "INVALID_CHART_INTERVAL"],
  ] as const) { await f.adapter.handle(f.request(patch)); assert.equal(f.replies.at(-1)!.code, code); }
  assert.strictEqual(f.runtime().view.document, before);
});

test("read exposes a whitelist with no script source, dates or future data", async () => {
  const f = fixture(); const request = f.request(); request.name = "candlescope_read_view";
  await f.adapter.handle(request);
  const result = f.replies[0]!.result!;
  assert.deepEqual(Object.keys(result).sort(), ["active", "chartType", "indicatorCount", "kind", "linkGroupId", "readiness", "replay", "revision", "session", "viewId", "windowId"].sort());
  assert.equal(result.readiness, "configured");
});

test("cancelled changes report uncertainty, and navigation invalidates pending operations", async () => {
  const f = fixture(); const request = f.request(); const task = f.adapter.handle(request); await Promise.resolve();
  await f.adapter.handle({ type: "cancel", requestId: request.requestId }); await task;
  assert.equal(f.replies.at(-1)!.code, "CONTROL_OUTCOME_UNKNOWN_READ_VIEW");
  f.commit();
  const next = f.request({ interval: "15m" }); const pending = f.adapter.handle(next); await Promise.resolve();
  f.adapter.update(f.runtime("replacement"), "window-1", "market"); await pending;
  assert.equal(f.replies.at(-1)!.code, "CONTROL_VIEW_REPLACED");
});

test("replay receipt waits for authoritative advancement and the committed idle state", async () => {
  const f = fixture(); let calls = 0;
  const replay = { key: "run:1", revision: 1, state: "PAUSED", busy: false, execute: async () => { calls++; } };
  f.adapter.update(f.runtime(), "window-1", "replay", replay);
  const request = f.request({ action: "next_bar" }); request.name = "candlescope_replay_control";
  const pending = f.adapter.handle(request); await Promise.resolve(); assert.equal(calls, 1); assert.equal(f.replies.length, 0);
  f.adapter.update(f.runtime(), "window-1", "replay", { ...replay, key: "run:2", revision: 2, busy: true });
  await Promise.resolve(); assert.equal(f.replies.length, 0);
  f.adapter.update(f.runtime(), "window-1", "replay", { ...replay, key: "run:3", revision: 2 }); await pending;
  assert.equal(f.replies[0]!.ok, true); assert.equal(f.replies[0]!.result!.scope, "shared_replay_clock");
  assert.equal(JSON.stringify(f.replies).includes('"revision":2'), false);
});
