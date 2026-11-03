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
  const state: ChartStudyClockState = { active: true, pending: false, committing: false, editing: false, followReady: true,
    studyId: "hs_input", revision: 4, cursorMs, minimumMs: 0, maximumMs: 1_000_000, ...patch };
  const calls: number[] = [];
  const modeCalls: Array<{ active: boolean; cursorMs: number | undefined }> = [];
  const port: ChartStudyClockPort = { read: () => state,
    move: async target => { calls.push(target); state.cursorMs = target; state.revision++; return true; },
    setMode: async (active, cursorMs) => { modeCalls.push({ active, cursorMs }); state.active = active;
      if (cursorMs !== undefined) state.cursorMs = cursorMs; state.revision++; return true; } };
  return { state, calls, modeCalls, port };
}
function nativeNetwork() {
  let order = 0;
  const receivers = new Map<string, (event: WorkspaceBusLinkEvent) => void>();
  const deferred: Array<{ resolve(): void; reject(error: Error): void }> = [];
  const wire: WorkspaceBusLinkEvent[] = [];
  const delayedWindows = new Set<string>();
  const delayedEvents: Array<{ windowId: string; event: WorkspaceBusLinkEvent }> = [];
  const deferNext = new Set<string>(), delayedPublications: Array<() => void> = [];
  let hold = false;
  const bus = (windowId: string) => ({ windowId, isNative: () => true,
    subscribeLink: (listener: (event: WorkspaceBusLinkEvent) => void) => { receivers.set(windowId, listener); return () => receivers.delete(windowId); },
    publishLink: (event: Omit<WorkspaceBusLinkEvent, "sourceWindowId">) => {
      const stamped = { ...event, sourceWindowId: windowId, eventId: `link-${++order}` }; wire.push(stamped);
      for (const [id, receive] of receivers) if (id !== windowId) {
        if (delayedWindows.has(id)) delayedEvents.push({ windowId: id, event: stamped }); else receive(stamped);
      }
    },
    publishOrderedLink: (event: WorkspaceBusLinkEvent) => new Promise<WorkspaceBusLinkEvent>((resolve, reject) => {
      const publish = () => {
        const stamped = { ...event, sourceWindowId: windowId, eventId: `link-${++order}` }; wire.push(stamped);
        for (const [id, receive] of receivers) if (id !== windowId) {
          if (delayedWindows.has(id)) delayedEvents.push({ windowId: id, event: stamped }); else receive(stamped);
        }
        if (hold) deferred.push({ resolve: () => resolve(stamped), reject }); else resolve(stamped);
      };
      if (deferNext.delete(windowId)) delayedPublications.push(publish); else publish();
    }),
  }) as unknown as WorkspaceBusClient;
  return { bus, wire, hold: () => { hold = true; }, release: (index = 0) => deferred.splice(index, 1)[0]!.resolve(),
    reject: (index = 0) => deferred.splice(index, 1)[0]!.reject(new Error("Ordering reply lost")),
    deferNextPublication: (windowId: string) => deferNext.add(windowId), dispatchDelayedPublication: () => delayedPublications.shift()!(),
    delayFor: (windowId: string) => delayedWindows.add(windowId),
    deliverDelayed: () => { const next = delayedEvents.shift()!; receivers.get(next.windowId)!(next.event); },
    deliverAllDelayed: () => { while (delayedEvents.length) { const next = delayedEvents.shift()!; receivers.get(next.windowId)!(next.event); } } };
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
  assert.equal(restored.linkGroups[DEFAULT_CHART_LINK_GROUP_ID]!.peerPolicy.studyMode, false);
  doc.linkGroups[DEFAULT_CHART_LINK_GROUP_ID]!.peerPolicy.studyMode = true;
  assert.equal(normalizeChartWorkspace(JSON.parse(JSON.stringify(doc))).linkGroups[DEFAULT_CHART_LINK_GROUP_ID]!.peerPolicy.studyMode, true);
});

test("mode and cursor policies are independent; mode-only resumes each chart's saved input and cut", async () => {
  const doc = document(false), links = new ChartStudyClockLinks(doc, "workspace");
  const a = clock(600_000), b = clock(120_000, { active: false, followReady: false, studyId: "hs_other" });
  links.register("cell-1", a.port, "workspace"); links.register("cell-2", b.port, "workspace");
  assert.equal(await links.publishUserMove(links.beginUserAction("cell-1", "workspace", "mode")), true);
  assert.deepEqual(b.modeCalls, []);
  doc.linkGroups[DEFAULT_CHART_LINK_GROUP_ID]!.peerPolicy.studyMode = true;
  assert.equal(await links.publishUserMove(links.beginUserAction("cell-1", "workspace", "mode")), true);
  assert.equal(b.state.active, true); assert.equal(b.state.cursorMs, 120_000); assert.equal(b.state.studyId, "hs_other");
  b.state.followReady = true; a.state.active = false;
  assert.equal(await links.publishUserMove(links.beginUserAction("cell-1", "workspace", "mode")), true);
  assert.equal(b.state.active, false); assert.equal(b.state.cursorMs, 120_000); assert.equal(b.state.studyId, "hs_other");
  assert.deepEqual(b.calls, []);
});

test("combined mode/cursor activation uses each target's input and refuses unprepared, editing or out-of-range targets", async () => {
  for (const [patch, status] of [
    [{}, "moved"], [{ studyId: null }, "unprepared"], [{ editing: true }, "editing"], [{ maximumMs: 500_000 }, "out-of-range"],
  ] as const) {
    const doc = document(), links = new ChartStudyClockLinks(doc, "workspace");
    doc.linkGroups[DEFAULT_CHART_LINK_GROUP_ID]!.peerPolicy.studyMode = true;
    const a = clock(), b = clock(120_000, { active: false, followReady: false, studyId: "hs_other", ...patch });
    links.register("cell-1", a.port, "workspace"); links.register("cell-2", b.port, "workspace");
    assert.equal(await links.publishUserMove(links.beginUserAction("cell-1", "workspace", "mode")), status === "moved");
    assert.equal(b.state.active, status === "moved"); assert.equal(b.state.cursorMs, status === "moved" ? 600_000 : 120_000);
    if (status !== "moved") {
      assert.deepEqual(b.modeCalls, []);
      assert.equal(links.getIssue("cell-1", "workspace")!.operation, "mode");
      assert.equal(links.getIssue("cell-1", "workspace")!.failed[0]!.status, status);
    } else assert.equal(b.state.studyId, "hs_other");
  }
});

test("a missing local chart and a throwing owner cannot be reported as synchronized", async () => {
  const links = new ChartStudyClockLinks(document(), "workspace"), a = clock();
  links.register("cell-1", a.port, "workspace");
  assert.equal(await links.publishUserMove(links.beginUserAction("cell-1", "workspace")), false);
  assert.equal(links.getIssue("cell-1", "workspace")!.failed[0]!.status, "unavailable");
  links.register("cell-2", { read: () => { throw new Error("Owner closed"); }, move: async () => { throw new Error("Must not write"); }, setMode: async () => { throw new Error("Must not write"); } }, "workspace");
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

test("isolated playback remains available without a linked leader or desktop bus", async () => {
  const links = new ChartStudyClockLinks(document(false), "workspace"), a = clock();
  links.register("cell-1", a.port, "workspace");
  assert.equal(links.canStartAutomatic("cell-1", "workspace"), true);
  const tick = links.beginUserAction("cell-1", "workspace", "tick");
  a.state.cursorMs = 660_000;
  assert.equal(await links.publishUserMove(tick), true); assert.equal(a.state.cursorMs, 660_000);
  assert.equal(links.canStartAutomatic("missing", "workspace"), false);
});

test("a recovered committed source publishes before its surface remounts, but an unmounted active target refuses following", async () => {
  const links = new ChartStudyClockLinks(document(), "workspace");
  const a = clock(600_000, { followReady: false }), b = clock(120_000);
  links.register("cell-1", a.port, "workspace"); links.register("cell-2", b.port, "workspace");
  assert.equal(await links.publishUserMove(links.beginUserAction("cell-1", "workspace")), true);
  assert.deepEqual(b.calls, [600_000]);
  b.state.followReady = false; a.state.cursorMs = 300_000;
  assert.equal(await links.publishUserMove(links.beginUserAction("cell-1", "workspace")), false);
  assert.deepEqual(b.calls, [600_000]);
  assert.equal(links.getIssue("cell-1", "workspace")!.failed[0]!.status, "unavailable");
  b.state.active = false;
  assert.equal(await links.publishUserMove(links.beginUserAction("cell-1", "workspace")), true);
  assert.deepEqual(b.calls, [600_000]);
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
  network.release(1); network.release(); await Promise.all([first, second]);
  assert.equal(a.state.cursorMs, 300_000); assert.equal(c.state.cursorMs, 300_000);
  assert.deepEqual(c.calls, [300_000]); assert.equal(left.getIssue("cell-1", "workspace"), null); releaseA(); releaseB();
});

test("an older incoming clock cannot overwrite a new local rewind while its ordering reply is pending", async () => {
  const doc = document(), network = nativeNetwork();
  const left = new ChartStudyClockLinks(doc, "workspace"), right = new ChartStudyClockLinks(doc, "workspace");
  const a = clock(600_000), b = clock(200_000);
  left.register("cell-1", a.port, "workspace"); right.register("cell-2", b.port, "workspace");
  const releaseA = left.connectWorkspaceBus(network.bus("main")), releaseB = right.connectWorkspaceBus(network.bus("second"));
  network.hold(); network.delayFor("second");
  const first = left.publishUserMove(left.beginUserAction("cell-1", "workspace"));
  await flush();
  b.state.cursorMs = 300_000; b.state.revision++;
  const second = right.publishUserMove(right.beginUserAction("cell-2", "workspace"));
  await flush(); network.deliverDelayed(); await flush();
  network.release(1); network.release(); await flush(); network.deliverAllDelayed(); await Promise.all([first, second]);
  assert.equal(a.state.cursorMs, 300_000); assert.equal(b.state.cursorMs, 300_000);
  releaseA(); releaseB();
});

test("a lost source ordering reply is not success, and queued clocks wait for an explicit confirmed retry", async () => {
  const doc = document(), network = nativeNetwork();
  const left = new ChartStudyClockLinks(doc, "workspace"), right = new ChartStudyClockLinks(doc, "workspace");
  const a = clock(600_000), b = clock(200_000);
  left.register("cell-1", a.port, "workspace"); right.register("cell-2", b.port, "workspace");
  const releaseA = left.connectWorkspaceBus(network.bus("main")), releaseB = right.connectWorkspaceBus(network.bus("second"));
  network.hold();
  const first = left.publishUserMove(left.beginUserAction("cell-1", "workspace")); await flush();
  b.state.cursorMs = 300_000; b.state.revision++;
  const second = right.publishUserMove(right.beginUserAction("cell-2", "workspace")); await flush();
  network.reject(); await flush(); network.release();
  assert.equal(await first, false); assert.equal(await second, false);
  assert.equal(a.state.cursorMs, 600_000); assert.equal(b.state.cursorMs, 300_000); assert.deepEqual(a.calls, []);
  assert.equal(left.getIssue("cell-1", "workspace")!.failed[0]!.status, "unavailable");
  a.state.active = false; left.cancelUserAction(left.beginUserAction("cell-1", "workspace"));
  b.state.cursorMs = 350_000;
  const liveSkipped = right.publishUserMove(right.beginUserAction("cell-2", "workspace")); await flush(); network.release();
  assert.equal(await liveSkipped, true); assert.deepEqual(a.calls, []); assert.equal(a.state.active, false);
  a.state.active = true;
  const retry = left.publishUserMove(left.beginUserAction("cell-1", "workspace")); await flush(); network.release();
  assert.equal(await retry, true); assert.equal(b.state.cursorMs, 600_000); assert.equal(left.getIssue("cell-1", "workspace"), null);
  releaseA(); releaseB();
});

test("an unknown exit order stays fenced while live, until an explicit mode retry confirms it", async () => {
  const doc = document(), network = nativeNetwork();
  doc.linkGroups[DEFAULT_CHART_LINK_GROUP_ID]!.peerPolicy.studyMode = true;
  const left = new ChartStudyClockLinks(doc, "workspace"), right = new ChartStudyClockLinks(doc, "workspace");
  const a = clock(600_000, { active: false }), b = clock(200_000);
  left.register("cell-1", a.port, "workspace"); right.register("cell-2", b.port, "workspace");
  const releaseA = left.connectWorkspaceBus(network.bus("main")), releaseB = right.connectWorkspaceBus(network.bus("second"));
  network.hold();
  const exit = left.publishUserMove(left.beginUserAction("cell-1", "workspace", "mode")); await flush();
  assert.equal(b.state.active, false);
  b.state.active = true;
  const enter = right.publishUserMove(right.beginUserAction("cell-2", "workspace", "mode")); await flush();
  network.reject(); await flush(); network.release();
  assert.equal(await exit, false); assert.equal(await enter, false); assert.equal(a.state.active, false);
  assert.equal(left.getIssue("cell-1", "workspace")!.operation, "mode");
  const retry = left.publishUserMove(left.beginUserAction("cell-1", "workspace", "mode")); await flush(); network.release();
  assert.equal(await retry, true); assert.equal(b.state.active, false); assert.equal(a.state.active, false);
  releaseA(); releaseB();
});

test("an automatic clock stamped after a newer mode exit cannot reenter or advance the exited charts", async () => {
  const doc = document(), network = nativeNetwork();
  doc.linkGroups[DEFAULT_CHART_LINK_GROUP_ID]!.peerPolicy.studyMode = true;
  const left = new ChartStudyClockLinks(doc, "workspace"), right = new ChartStudyClockLinks(doc, "workspace");
  const a = clock(600_000), b = clock(200_000);
  left.register("cell-1", a.port, "workspace"); right.register("cell-2", b.port, "workspace");
  const releaseA = left.connectWorkspaceBus(network.bus("main")), releaseB = right.connectWorkspaceBus(network.bus("second"));
  assert.equal(await right.publishUserMove(right.beginUserAction("cell-2", "workspace")), true);
  b.state.cursorMs = 260_000; network.deferNextPublication("second");
  const tick = right.publishUserMove(right.beginUserAction("cell-2", "workspace", "tick")); await flush();
  a.state.active = false;
  assert.equal(await left.publishUserMove(left.beginUserAction("cell-1", "workspace", "mode")), true);
  assert.equal(b.state.active, false);
  network.dispatchDelayedPublication(); await tick;
  assert.equal(a.state.active, false); assert.equal(b.state.active, false); assert.equal(a.state.cursorMs, 200_000);
  releaseA(); releaseB();
});

test("a new explicit clock preempts an automatic tick waiting for its source reply", async () => {
  const doc = document(), network = nativeNetwork();
  const left = new ChartStudyClockLinks(doc, "workspace"), right = new ChartStudyClockLinks(doc, "workspace");
  const a = clock(600_000), b = clock(200_000);
  left.register("cell-1", a.port, "workspace"); right.register("cell-2", b.port, "workspace");
  const releaseA = left.connectWorkspaceBus(network.bus("main")), releaseB = right.connectWorkspaceBus(network.bus("second"));
  assert.equal(await left.publishUserMove(left.beginUserAction("cell-1", "workspace")), true);
  network.hold(); a.state.cursorMs = 660_000;
  const tick = left.publishUserMove(left.beginUserAction("cell-1", "workspace", "tick")); await flush();
  b.state.cursorMs = 300_000;
  const rewind = right.publishUserMove(right.beginUserAction("cell-2", "workspace")); await flush();
  assert.equal(a.state.cursorMs, 300_000); // No wait for the old automatic reply.
  network.release(1); network.release(); await Promise.all([tick, rewind]);
  assert.equal(a.state.cursorMs, 300_000); assert.equal(b.state.cursorMs, 300_000);
  assert.equal(left.canStartAutomatic("cell-1", "workspace"), false);
  assert.equal(right.canStartAutomatic("cell-2", "workspace"), true);
  releaseA(); releaseB();
});

test("an old automatic publication arriving at the authority later cannot steal a newer explicit leader", async () => {
  const doc = document(), network = nativeNetwork();
  const left = new ChartStudyClockLinks(doc, "workspace"), right = new ChartStudyClockLinks(doc, "workspace");
  const a = clock(600_000), b = clock(200_000);
  left.register("cell-1", a.port, "workspace"); right.register("cell-2", b.port, "workspace");
  const releaseA = left.connectWorkspaceBus(network.bus("main")), releaseB = right.connectWorkspaceBus(network.bus("second"));
  assert.equal(await left.publishUserMove(left.beginUserAction("cell-1", "workspace")), true);
  a.state.cursorMs = 660_000; network.deferNextPublication("main");
  const tick = left.publishUserMove(left.beginUserAction("cell-1", "workspace", "tick")); await flush();
  b.state.cursorMs = 300_000;
  assert.equal(await right.publishUserMove(right.beginUserAction("cell-2", "workspace")), true);
  network.dispatchDelayedPublication(); await tick;
  assert.equal(a.state.cursorMs, 300_000); assert.equal(b.state.cursorMs, 300_000);
  assert.equal(left.canStartAutomatic("cell-1", "workspace"), false);
  assert.equal(right.canStartAutomatic("cell-2", "workspace"), true);
  assert.equal(left.getIssue("cell-1", "workspace"), null);
  releaseA(); releaseB();
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
