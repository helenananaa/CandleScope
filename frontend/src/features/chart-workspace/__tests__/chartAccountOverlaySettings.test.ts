import assert from "node:assert/strict";
import test from "node:test";
import { normalizeChartAccountOverlay } from "../chartAccountOverlaySettings.js";
import { applyLinkedAccountOverlayUpdate, cloneChartLinkSettings } from "../chartWorkspaceLinkModel.js";
import { createDefaultChartWorkspace, normalizeChartWorkspaceWithDiagnostics } from "../chartWorkspaceStorage.js";
import { DEFAULT_CHART_LINK_GROUP_ID, DEFAULT_CHART_LINK_GROUP_SETTINGS } from "../chartWorkspaceTypes.js";

test("legacy account overlays explicitly follow the panel without adding notes or links", () => {
  for (const schemaVersion of [7, 8]) {
    const legacy = { ...createDefaultChartWorkspace(), schemaVersion };
    for (const cell of Object.values(legacy.cells)) delete cell.accountOverlay;
    const result = normalizeChartWorkspaceWithDiagnostics(legacy);
    assert.equal(result.usedFallback, false);
    assert.equal(result.migratedFromSchemaVersion, schemaVersion);
    assert.deepEqual(result.document.cells["cell-1"]!.accountOverlay, { accountId: null, trades: true, positions: true, notes: false });
    for (const group of Object.values(result.document.linkGroups)) {
      assert.equal(group.peerPolicy.accountSource, false);
      assert.equal(group.peerPolicy.tradingOverlays, false);
      assert.equal(group.peerPolicy.noteOverlays, false);
    }
  }
});

test("an unlinked pinned account and display preferences persist without altering sibling charts", () => {
  const document = createDefaultChartWorkspace();
  const settings = { accountId: "account-a", trades: false, positions: true, notes: true };
  const changed = applyLinkedAccountOverlayUpdate(document, "cell-1", settings);
  assert.equal(changed.cells["cell-2"], document.cells["cell-2"]);
  assert.equal(changed.cells["cell-1"]!.session, document.cells["cell-1"]!.session);
  const restored = normalizeChartWorkspaceWithDiagnostics(JSON.parse(JSON.stringify(changed)));
  assert.equal(restored.usedFallback, false);
  assert.deepEqual(restored.document.cells["cell-1"]!.accountOverlay, settings);
  assert.equal(applyLinkedAccountOverlayUpdate(changed, "cell-1", settings), changed);
});

test("account, trade visibility, and note visibility use separate directed link channels", () => {
  const document = createDefaultChartWorkspace();
  const primary = document.linkGroups[DEFAULT_CHART_LINK_GROUP_ID]!;
  primary.peerPolicy = { ...primary.peerPolicy, accountSource: false, tradingOverlays: true, noteOverlays: false };
  document.linkGroups.child = { id: "child", name: "Child", color: "#123456", parentId: primary.id,
    peerPolicy: cloneChartLinkSettings(DEFAULT_CHART_LINK_GROUP_SETTINGS),
    receiveFromParent: { ...cloneChartLinkSettings(DEFAULT_CHART_LINK_GROUP_SETTINGS), accountSource: true, noteOverlays: true } };
  document.cells["cell-3"]!.linkGroupId = "child";
  document.cells["cell-4"]!.linkGroupId = null;
  document.cells["cell-2"]!.accountOverlay = { accountId: "b", trades: true, positions: false, notes: false };
  const changed = applyLinkedAccountOverlayUpdate(document, "cell-1", { accountId: "a", trades: false, positions: true, notes: true });
  assert.deepEqual(changed.cells["cell-2"]!.accountOverlay, { accountId: "b", trades: false, positions: false, notes: false });
  assert.deepEqual(changed.cells["cell-3"]!.accountOverlay, { accountId: "a", trades: true, positions: true, notes: true });
  assert.equal(changed.cells["cell-4"], document.cells["cell-4"]);
  const childEdit = applyLinkedAccountOverlayUpdate(changed, "cell-3", { accountId: "c", trades: true, positions: false, notes: false });
  assert.equal(childEdit.cells["cell-1"], changed.cells["cell-1"]);
  assert.equal(childEdit.cells["cell-2"], changed.cells["cell-2"]);
});

test("malformed preference inputs cannot enable links or manufacture an account id", () => {
  assert.deepEqual(normalizeChartAccountOverlay({ accountId: {}, trades: "false", positions: 0, notes: "yes" }), normalizeChartAccountOverlay());
  assert.equal(normalizeChartAccountOverlay({ accountId: " ", notes: true }).accountId, null);
});
