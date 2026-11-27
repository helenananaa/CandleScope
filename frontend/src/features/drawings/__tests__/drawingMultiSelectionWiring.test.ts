import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { isDrawingBodyHit } from "../drawingInteractionController.js";
import { shouldProjectVisibleSceneEntity } from "../useDrawingPersistenceLifecycle.js";

test("only a press on the drawing itself starts a group move; handles keep resizing one drawing", () => {
  for (const hit of [{}, { zone: "body" }, { zone: "center" }, { zone: "entry" }, { zone: "line" }, { zone: "horizontal" }, { zone: "vertical" }, { zone: "label" }, { body: true, pointIndex: 0 }, { pointIndex: -1 }]) {
    assert.equal(isDrawingBodyHit(hit), true, JSON.stringify(hit));
  }
  for (const hit of [{ pointIndex: 0 }, { pointIndex: 1 }, { handle: "tl" }, { zone: "tp" }, { zone: "sl" }, { zone: "left" }, { zone: "panel" }, { zone: "br" }]) {
    assert.equal(isDrawingBodyHit(hit), false, JSON.stringify(hit));
  }
});

test("drawings moving with a group leave the static scene while the overlay paints them", () => {
  const companions = new Set(["ln_2", "tx_3"]);
  assert.equal(shouldProjectVisibleSceneEntity("line", "ln_1", true, null, companions), true);
  assert.equal(shouldProjectVisibleSceneEntity("line", "ln_2", true, null, companions), false);
  assert.equal(shouldProjectVisibleSceneEntity("text", "tx_3", true, "ln_9", companions), false);
  assert.equal(shouldProjectVisibleSceneEntity("line", "ln_9", true, "ln_9", companions), false);
  // Without the dynamic overlay there is nothing else to paint them, so they stay.
  assert.equal(shouldProjectVisibleSceneEntity("line", "ln_2", false, null, companions), true);
  assert.equal(shouldProjectVisibleSceneEntity("line", "ln_2", true, null), true);
});

test("multi-selection shortcuts belong to the chart last pressed and skip text fields and dialogs", () => {
  const source = readFileSync(new URL("../interaction/useDrawingMultiSelection.ts", import.meta.url), "utf8");
  assert.match(source, /activeOwner !== ownerRef\.current/);
  assert.match(source, /isTextEditing\(\) \|\| editableTarget\(event\.target\) \|\| hasOpenOverlay\(\)/);
  const controller = readFileSync(new URL("../drawingInteractionController.ts", import.meta.url), "utf8");
  assert.match(controller, /multiSelection\.markActive\(\);/);
});

test("groups are unavailable in every replay training drawing scope and nowhere else", async () => {
  const { chartCellDrawingScopeBaseFromCell } = await import("../../chart-workspace/chartWorkspaceDrawingLink.js");
  const { drawingScopeAllowsGroups } = await import("../drawingScopeCapabilities.js");
  const session = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT" };
  const cell = { id: "cell-1", drawingLayerSet: "1", linkGroupId: "g1" };
  const linked = { peerPolicy: { drawings: true } };
  const replayWorkspace = "replay:prepared-abc:workspace-default";
  const plain = chartCellDrawingScopeBaseFromCell(replayWorkspace as never, cell as never, null, session as never);
  const shared = chartCellDrawingScopeBaseFromCell(replayWorkspace as never, cell as never, linked as never, session as never);
  for (const scope of [`${plain}__main`, `${shared}__main`, "replay-run:abc", "replay-review:r1:cell-1__main"]) {
    assert.equal(drawingScopeAllowsGroups(scope), false, scope);
  }
  const live = chartCellDrawingScopeBaseFromCell("default" as never, cell as never, null, session as never);
  const liveLinked = chartCellDrawingScopeBaseFromCell("ws-2" as never, cell as never, linked as never, session as never);
  for (const scope of [`${live}__main`, `${liveLinked}__main`, "BTCUSDT", "strategy-research:run-1"]) {
    assert.equal(drawingScopeAllowsGroups(scope), true, scope);
  }
  // The replay pages still build their scopes from these bases.
  const workspace = readFileSync(new URL("../../replay/ReplayChartWorkspace.tsx", import.meta.url), "utf8");
  assert.match(workspace, /chartCellDrawingScopeBase\(`replay:\$\{runId\}:/);
  const shell = readFileSync(new URL("../../replay/ReplayTrainingPageShell.tsx", import.meta.url), "utf8");
  assert.match(shell, /`replay-run:\$\{/);
  assert.match(shell, /`replay-review:\$\{/);
});
