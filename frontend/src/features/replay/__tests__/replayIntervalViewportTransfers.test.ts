import assert from "node:assert/strict";
import test from "node:test";
import { ReplayIntervalViewportTransfers } from "../replayIntervalViewportTransfers.js";
import { createDefaultChartWorkspace } from "../../chart-workspace/chartWorkspaceStorage.js";
import { applyChartLinkGroupPolicyUpdate } from "../../chart-workspace/chartWorkspaceLinkModel.js";

test("period capture targets only linked receiving cells whose interval changes", () => {
  const document = createDefaultChartWorkspace();
  const transfers = new ReplayIntervalViewportTransfers();
  const captured: [string, string][] = [];
  for (const [id, cell] of Object.entries(document.cells)) {
    cell.session.interval = "7m";
    transfers.register(id, interval => captured.push([id, interval]));
  }
  transfers.prepare(document, "cell-1", "90m");
  assert.deepEqual(captured, [], "default period links are disabled");
  for (const group of Object.values(document.linkGroups)) group.peerPolicy.interval = true;
  document.cells["cell-3"]!.session.interval = "90m";
  document.cells["cell-4"]!.linkGroupId = null;
  transfers.prepare(document, "cell-1", "90m");
  assert.deepEqual(captured, [["cell-2", "90m"]]);
});

test("stale cell cleanup cannot remove the new market's viewport receiver", () => {
  const document = createDefaultChartWorkspace();
  for (const group of Object.values(document.linkGroups)) group.peerPolicy.interval = true;
  const transfers = new ReplayIntervalViewportTransfers();
  const captured: string[] = [];
  const old = transfers.register("cell-2", () => captured.push("old"));
  const current = transfers.register("cell-2", () => captured.push("new"));
  old();
  transfers.prepare(document, "cell-1", "90m");
  assert.deepEqual(captured, ["new"]);
  current();
  transfers.prepare(document, "cell-1", "7m");
  assert.deepEqual(captured, ["new"]);
});

test("enabling a period policy captures the cells changed by that same policy transaction", () => {
  const document = createDefaultChartWorkspace();
  const transfers = new ReplayIntervalViewportTransfers();
  const captured: [string, string][] = [];
  for (const cell of Object.values(document.cells)) {
    cell.session.interval = "7m";
    transfers.register(cell.id, interval => captured.push([cell.id, interval]));
  }
  document.cells["cell-1"]!.session.interval = "90m";
  const groupId = document.cells["cell-1"]!.linkGroupId!;
  const next = applyChartLinkGroupPolicyUpdate(document, groupId, "peers", { interval: true });
  transfers.prepareDocumentChange(document, next);
  assert.deepEqual(captured, [["cell-2", "90m"], ["cell-3", "90m"], ["cell-4", "90m"]]);
  assert.equal(document.cells["cell-2"]!.session.interval, "7m", "preparation leaves the old surface in place");
  assert.equal(next.cells["cell-2"]!.session.interval, "90m");
  assert.equal(applyChartLinkGroupPolicyUpdate(next, groupId, "peers", { interval: true }), next);
});

test("a policy transaction changing the market never transfers the old market's viewport", () => {
  const document = createDefaultChartWorkspace();
  const next = structuredClone(document);
  next.cells["cell-2"]!.session = { ...next.cells["cell-2"]!.session, interval: "90m", symbol: "LTCUSDT" };
  document.cells["cell-2"]!.session.symbol = "SOLUSDT";
  const transfers = new ReplayIntervalViewportTransfers();
  transfers.register("cell-2", () => assert.fail("different market reused a viewport"));
  transfers.prepareDocumentChange(document, next);
});
