import assert from "node:assert/strict";
import test from "node:test";

import {
  ChartLinkCoordinator,
  type ChartLinkSurface,
} from "../chartLinkCoordinator.js";
import { chartWorkspaceCell } from "../chartWorkspaceDocument.js";
import { cloneChartLinkSettings } from "../chartWorkspaceLinkModel.js";
import { createDefaultChartWorkspace } from "../chartWorkspaceStorage.js";
import {
  DEFAULT_CHART_LINK_GROUP_ID,
  DEFAULT_CHART_LINK_GROUP_SETTINGS,
} from "../chartWorkspaceTypes.js";

function recordingSurface() {
  const crosshair: Array<number | null> = [];
  const ranges: Array<{ from: number; to: number }> = [];
  const readyListeners = new Set<(generation: number) => void>();
  let generation = 0;
  const surface: ChartLinkSurface = {
    setLinkedCrosshairTime: (time) => { crosshair.push(time); return true; },
    setLinkedVisibleTimeAnchor: () => true,
    setLinkedVisibleTimeRange: (range) => { ranges.push(range); return true; },
    subscribeLinkedViewportReady: (listener) => {
      readyListeners.add(listener);
      return () => { readyListeners.delete(listener); };
    },
  };
  return {
    surface,
    crosshair,
    ranges,
    signalReady: () => {
      generation += 1;
      for (const listener of readyListeners) listener(generation);
    },
  };
}

function hierarchicalDocument() {
  const document = createDefaultChartWorkspace();
  document.linkGroups["group-child"] = {
    id: "group-child",
    name: "确认组",
    color: "#8b5cf6",
    parentId: DEFAULT_CHART_LINK_GROUP_ID,
    peerPolicy: cloneChartLinkSettings(DEFAULT_CHART_LINK_GROUP_SETTINGS),
    receiveFromParent: cloneChartLinkSettings(DEFAULT_CHART_LINK_GROUP_SETTINGS),
  };
  chartWorkspaceCell(document, "cell-3").linkGroupId = "group-child";
  chartWorkspaceCell(document, "cell-4").linkGroupId = "group-child";
  return document;
}

test("explicit date navigation loads each time-linked target once, with no upward propagation", async () => {
  const document = hierarchicalDocument();
  const coordinator = new ChartLinkCoordinator(document);
  const calls: string[] = [];
  for (const cellId of ["cell-1", "cell-2", "cell-3", "cell-4"]) {
    coordinator.registerTimeNavigator(cellId, async (timeMs) => {
      calls.push(cellId);
      return { status: "located", requestedTimeMs: timeMs, actualTimeMs: timeMs, exact: true };
    });
  }
  await coordinator.seekToTime("cell-1", 120_000);
  assert.deepEqual(calls, ["cell-1", "cell-2", "cell-3", "cell-4"]);
  calls.length = 0;
  await coordinator.seekToTime("cell-3", 180_000);
  assert.deepEqual(calls, ["cell-3", "cell-4"]);
  calls.length = 0;
  document.linkGroups["group-child"]!.peerPolicy.dateRange = false;
  coordinator.updateDocument(document);
  await coordinator.seekToTime("cell-3", 240_000);
  assert.deepEqual(calls, ["cell-3"]);
});

test("date navigation isolates failed targets and unregisters disabled sources", async () => {
  const coordinator = new ChartLinkCoordinator(hierarchicalDocument());
  coordinator.registerTimeNavigator("cell-1", async (requestedTimeMs) => ({ status: "empty", requestedTimeMs }));
  coordinator.registerTimeNavigator("cell-2", async () => { throw new Error("offline"); });
  const unregister = coordinator.registerTimeNavigator("cell-3", async () => { throw new Error("must not call"); });
  unregister();
  const outcomes = await coordinator.seekToTime("cell-1", 120_000);
  assert.deepEqual(outcomes.map(({ cellId, result }) => [cellId, result.status]), [
    ["cell-1", "empty"], ["cell-2", "unavailable"],
  ]);
});

test("transient events fan out to source peers and descendants but never upward", () => {
  const document = hierarchicalDocument();
  const coordinator = new ChartLinkCoordinator(document);
  const parentPeer = recordingSurface();
  const child1 = recordingSurface();
  const child2 = recordingSurface();
  coordinator.register("cell-2", parentPeer.surface);
  coordinator.register("cell-3", child1.surface);
  coordinator.register("cell-4", child2.surface);

  coordinator.publishCrosshair("cell-1", 123);
  assert.deepEqual(parentPeer.crosshair, [123]);
  assert.deepEqual(child1.crosshair, [123]);
  assert.deepEqual(child2.crosshair, [123]);

  coordinator.publishCrosshair("cell-3", 456);
  assert.deepEqual(parentPeer.crosshair, [123]);
  assert.deepEqual(child2.crosshair, [123, 456]);
});

test("viewport failures stay isolated and report the original source group", () => {
  const document = hierarchicalDocument();
  const coordinator = new ChartLinkCoordinator(document);
  const healthy = recordingSurface();
  const unsupported = recordingSurface();
  unsupported.surface.setLinkedVisibleTimeRange = () => false;
  coordinator.register("cell-2", healthy.surface);
  coordinator.register("cell-3", unsupported.surface);

  coordinator.publishDateRange("cell-1", { from: 200, to: 100 });
  assert.deepEqual(healthy.ranges, [{ from: 100, to: 200 }]);
  assert.deepEqual(coordinator.getViewportIssue(), {
    group: DEFAULT_CHART_LINK_GROUP_ID,
    kind: "dateRange",
    sourceCellId: "cell-1",
    failedCellIds: ["cell-3"],
  });
});

test("an unmounted descendant catches up only to the latest applicable viewport", () => {
  const document = hierarchicalDocument();
  const coordinator = new ChartLinkCoordinator(document, "workspace-1");
  coordinator.publishDateRange("cell-1", { from: 100, to: 200 });
  coordinator.publishDateRange("cell-1", { from: 300, to: 400 });

  const child = recordingSurface();
  coordinator.register("cell-3", child.surface, "workspace-1");
  assert.deepEqual(child.ranges, [{ from: 300, to: 400 }]);
});

test("disabling a child receive channel invalidates retained parent viewports", () => {
  const document = hierarchicalDocument();
  const coordinator = new ChartLinkCoordinator(document, "workspace-1");
  coordinator.publishDateRange("cell-1", { from: 100, to: 200 });
  document.linkGroups["group-child"]!.receiveFromParent.dateRange = false;
  coordinator.updateDocument(document, "workspace-1");

  const child = recordingSurface();
  coordinator.register("cell-3", child.surface, "workspace-1");
  assert.deepEqual(child.ranges, []);
});

test("readiness generations reapply the retained viewport after a surface reset", () => {
  const document = hierarchicalDocument();
  const coordinator = new ChartLinkCoordinator(document, "workspace-1");
  const child = recordingSurface();
  coordinator.register("cell-3", child.surface, "workspace-1");
  coordinator.publishDateRange("cell-1", { from: 100, to: 200 });
  child.signalReady();
  assert.deepEqual(child.ranges, [
    { from: 100, to: 200 },
    { from: 100, to: 200 },
  ]);
});
