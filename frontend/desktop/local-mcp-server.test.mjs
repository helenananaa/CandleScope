import assert from "node:assert/strict";
import test from "node:test";
import { request as httpRequest } from "node:http";
import { startLocalMcpServer, MCP_PROTOCOL_VERSION, validateMcpToolCall } from "./local-mcp-server.mjs";

async function fixture(t, options = {}) {
  const calls = []; const audit = [];
  const server = await startLocalMcpServer({ invoke: async (name, args) => { calls.push({ name, args }); return { acknowledged: true }; }, onAudit: (event) => audit.push(event), ...options });
  t.after(() => server.close());
  const headers = { Authorization: `Bearer ${server.token}`, Accept: "application/json, text/event-stream", "Content-Type": "application/json" };
  const raw = (body, extra = {}) => fetch(server.endpoint, { method: "POST", ...extra, headers: { ...headers, ...extra.headers }, body: JSON.stringify(body) });
  const init = await raw({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: MCP_PROTOCOL_VERSION, capabilities: {}, clientInfo: { name: "test", version: "1" } } });
  assert.equal(init.status, 200);
  assert.equal((await init.json()).result.protocolVersion, MCP_PROTOCOL_VERSION);
  headers["Mcp-Session-Id"] = init.headers.get("mcp-session-id"); headers["MCP-Protocol-Version"] = MCP_PROTOCOL_VERSION;
  const call = async (method, params = {}, id = 2) => { const response = await raw({ jsonrpc: "2.0", id, method, params }); return { response, body: await response.json() }; };
  assert.equal((await raw({ jsonrpc: "2.0", method: "notifications/initialized" })).status, 202);
  return { server, calls, audit, raw, call, headers };
}

test("real HTTP negotiation, discovery, query and read-only rejection", async (t) => {
  const f = await fixture(t);
  assert.deepEqual((await f.call("tools/list")).body.result.tools.map((tool) => tool.name), ["candlescope_list_views", "candlescope_read_view"]);
  const read = await f.call("tools/call", { name: "candlescope_read_view", arguments: { windowId: "one", viewId: "chart-1" } });
  assert.equal(read.body.result.structuredContent.acknowledged, true);
  assert.equal(f.calls.length, 1);
  const reject = await f.call("tools/call", { name: "candlescope_set_chart", arguments: { windowId: "one", viewId: "chart-1", expectedRevision: "r1", operationId: "op-1", interval: "5m" } });
  assert.equal(reject.body.result.structuredContent.code, "CONTROL_PERMISSION_REQUIRED"); assert.equal(f.calls.length, 1);
  assert.equal(JSON.stringify(f.audit).includes(f.server.token), false);
});

test("identical retries apply once; conflicts fail before dispatch", async (t) => {
  const f = await fixture(t, { mode: "control" });
  const params = { name: "candlescope_replay_control", arguments: { windowId: "one", viewId: "run-1", expectedRevision: "r1", operationId: "op-1", action: "next_bar" } };
  const [one, two] = await Promise.all([f.call("tools/call", params, 3), f.call("tools/call", params, 4)]);
  assert.equal(f.calls.length, 1); assert.deepEqual(one.body.result, two.body.result);
  const conflict = await f.call("tools/call", { ...params, arguments: { ...params.arguments, action: "pause" } }, 5);
  assert.equal(conflict.body.result.structuredContent.code, "OPERATION_ID_CONFLICT"); assert.equal(f.calls.length, 1);
});

test("authentication, rebinding, origin, content type and protocol are rejected", async (t) => {
  const f = await fixture(t); const msg = { jsonrpc: "2.0", id: 3, method: "ping" };
  for (const [headers, status] of [
    [{ Authorization: "Bearer wrong" }, 401], [{ Origin: "https://evil.example" }, 403],
    [{ Origin: "null" }, 403],
    [{ "Content-Type": "text/plain" }, 415], [{ Accept: "application/json" }, 406],
    [{ "MCP-Protocol-Version": "unsupported" }, 400], [{ "Mcp-Session-Id": "missing" }, 404],
  ]) assert.equal((await f.raw(msg, { headers })).status, status, JSON.stringify(headers));
  const rebound = await new Promise((resolve, reject) => {
    const request = httpRequest(f.server.endpoint, { method: "POST", headers: { ...f.headers, Host: "evil.example" } }, (response) => { response.resume(); resolve(response.statusCode); });
    request.on("error", reject); request.end(JSON.stringify(msg));
  });
  assert.equal(rebound, 403);
  assert.equal((await fetch(f.server.endpoint, { headers: f.headers })).status, 405);
});

test("invalid argument variants cannot invoke application code", async (t) => {
  const f = await fixture(t, { mode: "control" });
  for (const args of [null, [], { windowId: "one" }, { windowId: "one", viewId: "x", unexpected: true }, { windowId: "../one", viewId: "x" }, JSON.parse('{"windowId":"one","viewId":"x","__proto__":"x"}')]) {
    assert.equal((await f.call("tools/call", { name: "candlescope_read_view", arguments: args })).body.error.code, -32602);
  }
  assert.equal((await f.call("tools/call", { name: "execute_javascript", arguments: {} })).body.error.code, -32602);
  assert.equal(f.calls.length, 0);
  assert.throws(() => validateMcpToolCall("candlescope_set_chart", { windowId: "one", viewId: "x", expectedRevision: "r1", operationId: "x", interval: "0m" }));
});

test("cancellation is bounded even if an adapter ignores abort", async (t) => {
  let dispatched; const started = new Promise((resolve) => { dispatched = resolve; });
  const f = await fixture(t, { mode: "control", invoke: () => { dispatched(); return new Promise(() => {}); } });
  const params = { name: "candlescope_replay_control", arguments: { windowId: "one", viewId: "run-1", expectedRevision: "r1", operationId: "op-1", action: "next_bar" } };
  const pending = f.call("tools/call", params, 8); await started;
  assert.equal((await f.raw({ jsonrpc: "2.0", method: "notifications/cancelled", params: { requestId: 8 } })).status, 202);
  const result = (await pending).body.result;
  assert.equal(result.structuredContent.code, "CONTROL_OUTCOME_UNKNOWN_READ_VIEW");
  assert.deepEqual((await f.call("tools/call", params, 9)).body.result, result);
});

test("timeout and session revocation settle pending reads", async (t) => {
  const f = await fixture(t, { timeoutMs: 20, invoke: () => new Promise(() => {}) });
  assert.equal((await f.call("tools/call", { name: "candlescope_list_views" })).body.result.structuredContent.code, "CONTROL_CANCELLED");
  assert.equal((await fetch(f.server.endpoint, { method: "DELETE", headers: f.headers })).status, 204);
  assert.equal((await f.raw({ jsonrpc: "2.0", id: 9, method: "ping" })).status, 404);
});
