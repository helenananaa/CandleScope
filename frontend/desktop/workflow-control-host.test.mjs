import assert from "node:assert/strict";
import test from "node:test";
import { EventEmitter } from "node:events";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { LocalMcpHost } from "./local-mcp-host.mjs";
import { WorkflowControlHost } from "./workflow-control-host.mjs";
import { DESKTOP_IPC } from "./ipc-contract.mjs";
import { MCP_TOOLS } from "./local-mcp-server.mjs";

async function fixture(t) {
  const directory = await mkdtemp(path.join(os.tmpdir(), "candlescope-workflow-"));
  const contents = new EventEmitter(), window = new EventEmitter();
  window.webContents = contents; window.isDestroyed = () => false;
  const sent = [];
  contents.send = (_channel, request) => sent.push(request);
  const manager = { windows: new Map([["main-window", window]]), options: {},
    windowIdForContents: (sender) => sender === contents ? "main-window" : null };
  const workflow = new WorkflowControlHost({ manager, channels: DESKTOP_IPC, directory,
    adapter: new URL("./control-service.mjs", import.meta.url).pathname, executable: process.execPath });
  const host = new LocalMcpHost({ workflow });
  t.after(async () => { await host.close(); assert.ok(directory.startsWith(path.join(os.tmpdir(), "candlescope-workflow-"))); await rm(directory, { recursive: true, force: true }); });
  workflow.ready("main-window");
  return { host, workflow, directory, contents, sent };
}

test("chart permission does not grant workflow access; workflow reads cannot edit", async (t) => {
  const { host, workflow, directory } = await fixture(t);
  assert.equal(host.status().mode, "off");
  await assert.rejects(readFile(path.join(directory, "connection.json")), { code: "ENOENT" });
  await host.setMode("control");
  assert.equal(workflow.service, null);
  assert.equal(MCP_TOOLS.length, 4);
  await host.setMode("read", true);
  assert.equal(host.status().workflow.enabled, true);
  assert.deepEqual(workflow.service.capabilities().scopes, ["observe"]);
  await assert.rejects(workflow.service.call("app.execute", { windowId: "main-window" }), { code: "SCOPE_DENIED" });
  assert.throws(() => workflow.service.fileCall("main-window", "begin", {}), { code: "SCOPE_DENIED" });
  await host.setMode("off");
  assert.equal(host.status().workflow.enabled, false);
  await assert.rejects(readFile(path.join(directory, "connection.json")), { code: "ENOENT" });
});

test("rotation invalidates workflow tokens, pending replies and files without accumulating listeners", async (t) => {
  const { host, workflow, directory, contents, sent } = await fixture(t);
  await host.setMode("control", true);
  const first = workflow.service;
  const old = JSON.parse(await readFile(path.join(directory, "connection.json"), "utf8"));
  const args = { requestId: "same-id", windowId: "main-window", groupId: "test", command: "mutate", expectedContext: "current" };
  await first.call("app.execute", args);
  await host.setMode("read", true);
  assert.equal(first.closed, true);
  await assert.rejects(fetch(`${old.endpoint}/call`));
  await host.setMode("control", true);
  const current = workflow.service;
  assert.notEqual(current.token, old.token);
  await current.call("app.execute", args);
  current.acceptResult("main-window", { id: args.requestId, instanceId: old.instanceId, final: true, result: { state: "applied" } });
  assert.equal((await current.call("request.get", { requestId: args.requestId })).final, false);
  const request = sent.at(-1);
  current.acceptResult("main-window", { id: request.id, instanceId: request.instanceId, final: true, result: { state: "applied" } });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal((await current.call("request.get", { requestId: args.requestId })).final, true);
  assert.equal(contents.listenerCount("did-start-loading"), 0);
  workflow.disconnect("main-window");
  await assert.rejects(current.call("app.commands", { windowId: "main-window" }), { code: "WINDOW_UNAVAILABLE" });
  await host.setMode("off");
  assert.equal(new LocalMcpHost().status().mode, "off");
});

test("failed workflow startup leaves both transports off and changes remain serialized", async (t) => {
  let active = false;
  const workflow = { status: () => ({ enabled: active }), close: async () => { active = false; },
    start: async () => { active = true; throw new Error("WORKFLOW_START_FAILED"); } };
  const host = new LocalMcpHost({ workflow }); t.after(() => host.close());
  await host.setMode("read");
  const previous = host.status().endpoint;
  await assert.rejects(host.setMode("control", true), /WORKFLOW_START_FAILED/);
  assert.equal(host.status().mode, "off"); assert.equal(active, false);
  await assert.rejects(fetch(previous));
  const results = await Promise.all([host.setMode("control"), host.setMode("off")]);
  assert.equal(results.at(-1).mode, "off");
  await assert.rejects(host.setMode("read", "yes"), /INVALID_CONTROL_MODE/);
});
