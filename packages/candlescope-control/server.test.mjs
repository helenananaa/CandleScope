import assert from "node:assert/strict";
import test from "node:test";
import { EventEmitter } from "node:events";
import { mkdtemp, rm } from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { createHash } from "node:crypto";
import { Client } from "@modelcontextprotocol/client";
import { StdioClientTransport } from "@modelcontextprotocol/client/stdio";
import { DesktopControlService } from "../../frontend/desktop/control-service.mjs";
import { DESKTOP_IPC } from "../../frontend/desktop/ipc-contract.mjs";
import { ControlClient } from "./client.mjs";
import { randomUUID } from "node:crypto";

test("missing app connection explains the setup/reconnect action without exposing credentials", async () => {
  const client = new ControlClient(path.join(os.tmpdir(), `candlescope-absent-${randomUUID()}.json`));
  await assert.rejects(client.connect(), (error) => error.code === "CONTROL_APP_OFFLINE" && error.message.includes("Settings > AI connection"));
});

for (const edit of [true, false]) test(`MCP stdio negotiates and exposes only granted tools (edit=${edit})`, async (t) => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "candlescope-mcp-"));
  const contents = new EventEmitter(); const window = new EventEmitter();
  window.webContents = contents; window.isDestroyed = () => false;
  const manager = { windows: new Map([["main-window", window]]), options: {}, windowIdForContents: () => "main-window" };
  const desktop = new DesktopControlService({ manager, channels: DESKTOP_IPC, edit });
  desktop.ready("main-window");
  let configurations = 0;
  contents.send = (_channel, message) => {
    if (message.method === "workspace.configure") configurations++;
    queueMicrotask(() => desktop.acceptResult("main-window", { id: message.id, instanceId: message.instanceId, final: true,
      result: message.method === "workspace.inspect" ? { state: "ready", snapshot: { workspaceId: "w", revision: 0 } }
        : { state: "ready", revision: 1 } }));
  };
  const file = await desktop.start(directory);
  const transport = new StdioClientTransport({ command: process.execPath,
    args: [path.resolve("cli.mjs"), "mcp", "--connection", file], stderr: "pipe" });
  const client = new Client({ name: "control-test", version: "1.0.0" });
  t.after(async () => { await client.close(); await transport.close(); await desktop.close();
    assert.ok(directory.startsWith(path.join(os.tmpdir(), "candlescope-mcp-"))); await rm(directory, { recursive: true, force: true }); });
  await client.connect(transport);
  const listing = await client.listTools();
  assert.deepEqual(listing.tools.map((tool) => tool.name).sort(), ["app_capabilities", "app_commands", ...(edit ? ["app_execute", "app_open"] : []), "app_query", "chart_capture", ...(edit ? ["file_begin", "file_commit"] : []), "file_read", ...(edit ? ["file_remove", "file_write"] : []), "request_get", ...(edit ? ["workspace_configure"] : []), "workspace_inspect"]);
  const inspection = await client.callTool({ name: "workspace_inspect", arguments: { windowId: "main-window" } });
  assert.equal(inspection.structuredContent.snapshot.workspaceId, "w");
  const configuration = { requestId: "sdk-edit", workspaceId: "w", windowId: "main-window", expectedRevision: 0,
    charts: [{ cellId: "cell-1", session: { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1h" }, indicators: [{ name: "EMA", period: 20 }] }] };
  if (!edit) {
    const direct = new ControlClient(file); await direct.connect();
    await assert.rejects(direct.call("workspace.configure", configuration), { code: "SCOPE_DENIED" });
    await assert.rejects(direct.call("file.begin", { windowId: "main-window" }), { code: "SCOPE_DENIED" });
    assert.equal(configurations, 0); return;
  }
  await client.callTool({ name: "workspace_configure", arguments: configuration });
  await client.callTool({ name: "workspace_configure", arguments: configuration });
  assert.equal(configurations, 1);
  const bytes = Buffer.from("a".repeat(40_000));
  const begin = await client.callTool({ name: "file_begin", arguments: { windowId: "main-window", uploadId: "file-sdk", name: "example.csv", mimeType: "text/csv", size: bytes.length, sha256: createHash("sha256").update(bytes).digest("hex") } });
  const fileRef = begin.structuredContent.fileRef;
  for (let offset = 0; offset < bytes.length; offset += 32768) {
    const result = await client.callTool({ name: "file_write", arguments: { windowId: "main-window", fileRef, offset, data: bytes.subarray(offset, offset + 32768).toString("base64") } }); assert.notEqual(result.isError, true);
  }
  const committed = await client.callTool({ name: "file_commit", arguments: { windowId: "main-window", fileRef } }); assert.equal(committed.structuredContent.committed, true);
  const part = await client.callTool({ name: "file_read", arguments: { windowId: "main-window", fileRef, offset: 32768 } }); assert.deepEqual(Buffer.from(part.structuredContent.data, "base64"), bytes.subarray(32768));
  desktop.disconnect("main-window"); desktop.ready("main-window");
  const expired = await client.callTool({ name: "file_read", arguments: { windowId: "main-window", fileRef, offset: 0 } }); assert.equal(expired.isError, true);
  const receipt = await client.callTool({ name: "request_get", arguments: { requestId: "sdk-edit" } });
  assert.equal(receipt.structuredContent.state, "ready");
  assert.equal(receipt.structuredContent.final, true);
  const denied = await client.callTool({ name: "workspace_inspect", arguments: { windowId: "not-a-window" } });
  assert.equal(denied.isError, true);
});

test("client rejects non-loopback descriptors before making a request", async (t) => {
  const { writeFile } = await import("node:fs/promises");
  const directory = await mkdtemp(path.join(os.tmpdir(), "candlescope-mcp-"));
  t.after(async () => { assert.ok(directory.startsWith(path.join(os.tmpdir(), "candlescope-mcp-"))); await rm(directory, { recursive: true, force: true }); });
  const file = path.join(directory, "connection.json");
  await writeFile(file, JSON.stringify({ schema: "candlescope.control-connection/1", endpoint: "http://evil.example:1234", token: "a".repeat(64), instanceId: "b".repeat(32) }));
  await assert.rejects(new ControlClient(file).connect(), /Invalid local/);
});
