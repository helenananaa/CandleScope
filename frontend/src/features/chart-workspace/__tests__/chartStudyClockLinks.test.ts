import assert from "node:assert/strict";
import test from "node:test";
import { ChartStudyClockLinks, type ChartStudyClockPort, type ChartStudyClockState } from "../chartStudyClockLinks.js";
import { createDefaultChartWorkspace, normalizeChartWorkspace } from "../chartWorkspaceStorage.js";
import { chartWorkspaceCell } from "../chartWorkspaceDocument.js";
import { createChartWorkspaceLayoutTree } from "../chartWorkspaceLayout.js";
import { DEFAULT_CHART_LINK_GROUP_ID } from "../chartWorkspaceTypes.js";
import type { WorkspaceBusClient, WorkspaceBusLinkEvent } from "../workspaceBus.js";

function document(enabled = true) {
  const result = createDefaultChartWorkspace();
  result.windows["main-window"]!.layoutTree = createChartWorkspaceLayoutTree("quad");
  for (const cell of Object.values(result.cells)) cell.linkGroupId = null;
  result.linkGroups[DEFAULT_CHART_LINK_GROUP_ID]!.peerPolicy.studyCursor = enabled;
  chartWorkspaceCell(result, "cell-1").linkGroupId = DEFAULT_CHART_LINK_GROUP_ID;
  chartWorkspaceCell(result, "cell-2").linkGroupId = DEFAULT_CHART_LINK_GROUP_ID;
  return result;
}
function clock(cursorMs = 600_000, patch: Partial<ChartStudyClockState> = {}) {
  const state: ChartStudyClockState = { active: true, pending: false, committing: false, editing: false,
    studyId: "hs_input", revision: 4, cursorMs, minimumMs: 0, maximumMs: 1_000_000, ...patch };
  const calls: number[] = [];
  const port: ChartStudyClockPort = { read: () => state, move: async target => { calls.push(target); state.cursorMs = target; state.revision++; return true; } };
  return { state, calls, port };
}
function nativeNetwork() {
  let order = 0;
  const receivers = new Map<string, (event: WorkspaceBusLinkEvent) => void>();
  const deferred: Array<() => void> = [];
  const wire: WorkspaceBusLinkEvent[] = [];
  let hold = false;
  const bus = (windowId: string) => ({ windowId, isNative: () => true,
    subscribeLink: (listener: (event: WorkspaceBusLinkEvent) => void) => { receivers.set(windowId, listener); return () => receivers.delete(windowId); },
    publishLink: (event: Omit<WorkspaceBusLinkEvent, "sourceWindowId">) => {
      const stamped = { ...event, sourceWindowId: windowId, eventId: `link-${++order}` }; wire.push(stamped);
      for (const [id, receive] of receivers) if (id !== windowId) receive(stamped);
    },
    publishOrderedLink: (event: WorkspaceBusLinkEvent) => new Promise<WorkspaceBusLinkEvent>(resolve => {
      const stamped = { ...event, sourceWindowId: windowId, eventId: `link-${++order}` }; wire.push(stamped);
      for (const [id, receive] of receivers) if (id !== windowId) receive(stamped);
      if (hold) deferred.push(() => resolve(stamped)); else resolve(stamped);
    }),
  }) as unknown as WorkspaceBusClient;
  return { bus, wire, hold: () => { hold = true; }, release: (index = 0) => deferred.splice(index, 1)[0]!() };
}
const flush = () => new Promise<void>(resolve => setImmediate(resolve));

test("legacy documents default cursor links off; an explicit choice survives the actual workspace restore", () => {
  const doc = document();
  delete doc.linkGroups[DEFAULT_CHART_LINK_GROUP_ID]!.peerPolicy.studyCursor;
  assert.equal(normalizeChartWorkspace(doc).linkGroups[DEFAULT_CHART_LINK_GROUP_ID]!.peerPolicy.studyCursor, false);
  doc.linkGroups[DEFAULT_CHART_LINK_GROUP_ID]!.peerPolicy.studyCursor = true;
  const restored = normalizeChartWorkspace(JSON.parse(JSON.stringify(doc)));
  assert.equal(restored.linkGroups[DEFAULT_CHART_LINK_GROUP_ID]!.peerPolicy.studyCursor, true);
  assert.equal(restored.linkGroups[DEFAULT_CHART_LINK_GROUP_ID]!.receiveFromParent.studyCursor, false);
});

test("a missing local chart and a throwing owner cannot be reported as synchronized", async () => {
  const links = new ChartStudyClockLinks(document(), "workspace"), a = clock();
  links.register("cell-1", a.port, "workspace");
  assert.equal(await links.publishUserMove(links.beginUserAction("cell-1", "workspace")), false);
  assert.equal(links.getIssue("cell-1", "workspace")!.failed[0]!.status, "unavailable");
  links.register("cell-2", { read: () => { throw new Error("Owner closed"); }, move: async () => { throw new Error("Must not write"); } }, "workspace");
  assert.equal(await links.publishUserMove(links.beginUserAction("cell-1", "workspace")), false);
  assert.equal(links.getIssue("cell-1", "workspace")!.failed[0]!.status, "unavailable");
});

test("disabled cursor policy leaves siblings unchanged; enabled policy uses each target's absolute cut", async () => {
  const doc = document(false), links = new ChartStudyClockLinks(doc, "workspace");
  const a = clock(), b = clock(120_000); links.register("cell-1", a.port, "workspace"); links.register("cell-2", b.port, "workspace");
  assert.equal(await links.publishUserMove(links.beginUserAction("cell-1", "workspace")), true);
  assert.deepEqual(b.calls, []);
  doc.linkGroups[DEFAULT_CHART_LINK_GROUP_ID]!.peerPolicy.studyCursor = true;
  assert.equal(await links.publishUserMove(links.beginUserAction("cell-1", "workspace")), true);
  assert.deepEqual(b.calls, [600_000]); assert.equal(a.state.revision, 4);
});

test("a closed layout cell is excluded even before its old renderer registration is released", async () => {
  const doc = document(), links = new ChartStudyClockLinks(doc, "workspace"), a = clock(), b = clock(120_000);
  links.register("cell-1", a.port, "workspace"); links.register("cell-2", b.port, "workspace");
  doc.windows["main-window"]!.layoutTree = createChartWorkspaceLayoutTree("single");
  links.updateDocument(doc, "workspace");
  assert.equal(await links.publishUserMove(links.beginUserAction("cell-1", "workspace")), true);
  assert.deepEqual(b.calls, []); assert.equal(links.getIssue("cell-1", "workspace"), null);
});

test("inactive, pending, editing and out-of-range peers do not enter or clamp a study", async () => {
  for (const [patch, status] of [
    [{ active: false }, "inactive"], [{ pending: true }, "unavailable"], [{ editing: true }, "editing"],
    [{ maximumMs: 500_000 }, "out-of-range"],
  ] as const) {
    const links = new ChartStudyClockLinks(document(), "workspace"), a = clock(), b = clock(120_000, patch);
    links.register("cell-1", a.port, "workspace"); links.register("cell-2", b.port, "workspace");
    assert.equal(await links.publishUserMove(links.beginUserAction("cell-1", "workspace")), status === "inactive");
    assert.deepEqual(b.calls, []); assert.equal(b.state.cursorMs, 120_000);
    if (status === "inactive") assert.equal(links.getIssue("cell-1", "workspace"), null);
    else assert.equal(links.getIssue("cell-1", "workspace")!.failed[0]!.status, status);
  }
});

test("an unfinished source write is never published, while a target can queue a newer cut through its durable port", async () => {
  const links = new ChartStudyClockLinks(document(), "workspace"), a = clock(600_000, { committing: true }), b = clock(120_000, { committing: true });
  links.register("cell-1", a.port, "workspace"); links.register("cell-2", b.port, "workspace");
  assert.equal(await links.publishUserMove(links.beginUserAction("cell-1", "workspace")), false);
  assert.deepEqual(b.calls, []);
  a.state.committing = false;
  assert.equal(await links.publishUserMove(links.beginUserAction("cell-1", "workspace")), true);
  assert.deepEqual(b.calls, [600_000]);
});

test("remote durable acknowledgements can arrive before the source IPC returns, without feedback publication", async () => {
  const network = nativeNetwork(), doc = document();
  const a = clock(), b = clock(120_000), left = new ChartStudyClockLinks(doc, "workspace"), right = new ChartStudyClockLinks(doc, "workspace");
  left.register("cell-1", a.port, "workspace"); right.register("cell-2", b.port, "workspace");
  const releaseA = left.connectWorkspaceBus(network.bus("main")), releaseB = right.connectWorkspaceBus(network.bus("second"));
  network.hold(); const result = left.publishUserMove(left.beginUserAction("cell-1", "workspace"));
  await flush(); assert.equal(b.state.cursorMs, a.state.cursorMs);
  assert.equal(network.wire.filter(event => event.kind === "studyCursor").length, 1);
  network.release(); assert.equal(await result, true);
  assert.equal(left.getIssue("cell-1", "workspace"), null); releaseA(); releaseB();
});

test("a delayed old source IPC result cannot overwrite a newer received cursor on local peers", async () => {
  const doc = document();
  chartWorkspaceCell(doc, "cell-3").linkGroupId = DEFAULT_CHART_LINK_GROUP_ID;
  const network = nativeNetwork(), left = new ChartStudyClockLinks(doc, "workspace"), right = new ChartStudyClockLinks(doc, "workspace");
  const a = clock(600_000), b = clock(200_000), c = clock(100_000);
  left.register("cell-1", a.port, "workspace"); left.register("cell-3", c.port, "workspace"); right.register("cell-2", b.port, "workspace");
  const releaseA = left.connectWorkspaceBus(network.bus("main")), releaseB = right.connectWorkspaceBus(network.bus("second"));
  network.hold(); const first = left.publishUserMove(left.beginUserAction("cell-1", "workspace")); await flush();
  b.state.cursorMs = 300_000; b.state.revision++;
  const second = right.publishUserMove(right.beginUserAction("cell-2", "workspace")); await flush();
  assert.equal(c.state.cursorMs, 300_000);
  network.release(1); await second; network.release(); await first;
  assert.equal(a.state.cursorMs, 300_000); assert.equal(c.state.cursorMs, 300_000);
  assert.deepEqual(c.calls, [300_000]); assert.equal(left.getIssue("cell-1", "workspace"), null); releaseA(); releaseB();
});

test("owner changes and replaced registrations fence an in-flight target acknowledgement", async () => {
  const links = new ChartStudyClockLinks(document(), "workspace"), a = clock(), b = clock();
  let finish: ((value: boolean) => void) | undefined;
  b.port.move = () => new Promise(resolve => { finish = resolve; });
  links.register("cell-1", a.port, "workspace"); const unregister = links.register("cell-2", b.port, "workspace");
  const result = links.publishUserMove(links.beginUserAction("cell-1", "workspace"));
  unregister(); links.register("cell-2", clock(10).port, "workspace"); finish!(true);
  assert.equal(await result, false);
  assert.equal(links.getIssue("cell-1", "workspace")!.failed[0]!.status, "superseded");
  const stale = links.beginUserAction("cell-1", "workspace"); links.updateDocument(document(), "other");
  assert.equal(await links.publishUserMove(stale), false); assert.equal(links.getIssue("cell-1", "workspace"), null);
});
