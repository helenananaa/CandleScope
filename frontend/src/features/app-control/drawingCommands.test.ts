import assert from "node:assert/strict";
import test from "node:test";
import type { ChartSurfaceActions } from "../../chart-adapter/useChartSurfaceRuntime.js";
import type { DrawingRuntime } from "../drawings/useDrawingRuntime.js";
import { createEmptyDrawingDocument } from "../drawings/core/drawingDocument.js";
import { AppCommandRegistry } from "./commandRegistry.js";
import { drawingCommands } from "./drawingCommands.js";

test("drawing discovery exposes scope readiness and rejects writes across a surface transition", async () => {
  let ready = false;
  let calls = 0;
  let preparations = 0;
  const document = createEmptyDrawingDocument("dataset__main");
  const surface = { actions: { getDrawingPaneApis: () => new Map([["main", {
    objects: { getObjectDocument: () => document },
    control: { isReady: () => ready, prepare: () => { preparations++; return false; }, readiness: () => ({ ready }), applyCommands: () => { calls++; return { committed: true, surfaceSynchronized: true, revision: 1 }; }, history: () => { calls++; return true; } },
  }]]) } as unknown as ChartSurfaceActions };
  const runtime = { view: {}, actions: {} } as unknown as DrawingRuntime;
  const registry = new AppCommandRegistry();
  registry.register(drawingCommands("imported", surface, runtime, "dataset"));
  const context = () => registry.list()[0]!.contextToken;
  const write = (expectedContext: string) => registry.execute({ id: "edit", method: "app.execute", params: {
    windowId: "window", groupId: "drawings:imported", command: "apply", requestId: "edit", expectedContext,
    args: { paneId: "main", scopeKey: document.scopeKey, expectedRevision: 0, commands: [{ type: "clear" }] },
  } }, "window");
  const before = context();
  assert.equal(registry.list()[0]!.commands.find((row) => row.name === "apply")!.available, false);
  assert.equal((await write(before)).message, "COMMAND_DISABLED");
  const inspection = await registry.execute({ id: "read", method: "app.query", params: { windowId: "window", groupId: "drawings:imported", command: "inspect" } }, "window");
  assert.equal((inspection.snapshot as { panes: { ready: boolean }[] }).panes[0]!.ready, false);
  assert.equal(calls, 0);
  const prepared = await registry.execute({ id: "prepare", method: "app.execute", params: {
    windowId: "window", groupId: "drawings:imported", command: "prepare", requestId: "prepare", expectedContext: context(), args: { paneId: "main" },
  } }, "window");
  assert.deepEqual(prepared.output, { ready: false });
  assert.equal(preparations, 1);
  assert.equal(calls, 0);
  ready = true;
  assert.notEqual(context(), before);
  assert.equal((await write(before)).message, "CONTEXT_CONFLICT");
  assert.equal((await write(context())).state, "applied");
  assert.equal(calls, 1);
  ready = false;
  assert.equal((await write(context())).message, "COMMAND_DISABLED");
  assert.equal(calls, 1);
});
