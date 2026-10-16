import http from "node:http";
import { randomBytes, timingSafeEqual } from "node:crypto";

// Deliberately a local, opt-in transport. No HTTP forwarding, file access,
// arbitrary evaluation, or order execution is part of this tool surface.
export const MCP_PROTOCOL_VERSION = "2025-06-18";
const MAX_BODY = 64 * 1024;
const MAX_RESULT = 2 * 1024 * 1024;
const MAX_SESSIONS = 16;
const MAX_OPERATIONS = 256;
const object = (value) => !!value && typeof value === "object" && !Array.isArray(value);
const identifier = (value) => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/.test(value);
const stringId = { type: "string", minLength: 1, maxLength: 160 };
const schema = (properties, required = Object.keys(properties)) => ({ type: "object", properties, required, additionalProperties: false });
const target = { windowId: stringId, viewId: stringId };
const mutation = { ...target, expectedRevision: stringId, operationId: stringId };

export const MCP_TOOLS = Object.freeze([
  { name: "candlescope_list_views", title: "List CandleScope views", description: "List registered open chart/replay views. Use the exact windowId and viewId returned; no implicit active-chart target.", inputSchema: schema({}), annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false } },
  { name: "candlescope_read_view", title: "Read CandleScope view", description: "Read current chart configuration and revealed replay state. Returns the revision required for a change. No unrevealed replay data or script source.", inputSchema: schema(target), annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false } },
  { name: "candlescope_set_chart", title: "Change one chart", description: "Set this chart's interval or representation. Requires control permission and a fresh revision. Linked charts follow the user's existing link settings; the receipt identifies changed views. Reuse operationId only for an identical retry.", inputSchema: schema({ ...mutation, interval: { type: "string", maxLength: 32 }, chartType: { type: "string", maxLength: 64 } }, Object.keys(mutation)), annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false } },
  { name: "candlescope_replay_control", title: "Control simulated replay", description: "Pause or advance one revealed replay bar on the exact run/view. Advances the shared clock for all markets and may fill existing simulated orders; it cannot submit new orders. Requires control permission and a fresh revision. An admitted clock advance completes atomically; cancellation cannot undo it. Read the view to reconcile an uncertain response.", inputSchema: schema({ ...mutation, action: { type: "string", enum: ["pause", "next_bar"] } }), annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false } },
]);

export function validateMcpToolCall(name, args) {
  const tool = MCP_TOOLS.find((item) => item.name === name);
  if (!tool || !object(args)) throw new TypeError("Unknown tool or invalid arguments");
  const { properties, required } = tool.inputSchema;
  if (Object.keys(args).some((key) => !Object.hasOwn(properties, key)) || required.some((key) => !Object.hasOwn(args, key))) {
    throw new TypeError("Unexpected or missing tool arguments");
  }
  for (const [key, value] of Object.entries(args)) {
    if (Object.hasOwn(mutation, key) && !identifier(value)) throw new TypeError(`Invalid ${key}`);
  }
  if (name === "candlescope_set_chart") {
    if (args.interval === undefined && args.chartType === undefined) throw new TypeError("Specify interval or chartType");
    if (args.interval !== undefined && (typeof args.interval !== "string" || !/^[1-9][0-9]{0,5}[smhdwM]$/.test(args.interval))) throw new TypeError("Invalid interval");
    if (args.chartType !== undefined && (typeof args.chartType !== "string" || !/^[a-z][a-z0-9-]{0,63}$/.test(args.chartType))) throw new TypeError("Invalid chartType");
  }
  if (name === "candlescope_replay_control" && !["pause", "next_bar"].includes(args.action)) throw new TypeError("Invalid replay action");
  return tool;
}

const rpcError = (id, code, message) => ({ jsonrpc: "2.0", id, error: { code, message } });
const rpcResult = (id, result) => ({ jsonrpc: "2.0", id, result });
const toolResult = (value, isError = false) => ({ content: [{ type: "text", text: JSON.stringify(value) }], structuredContent: value, isError });
const stableKey = (name, args) => JSON.stringify([name, Object.fromEntries(Object.entries(args).sort(([a], [b]) => a.localeCompare(b)))]);

function authorized(request, secret) {
  const actual = Buffer.from(request.headers.authorization ?? "");
  const expected = Buffer.from(`Bearer ${secret}`);
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

/** Stateful Streamable HTTP (JSON responses, no server-initiated SSE).
 * invoke receives an AbortSignal. Cancellation is advisory after admission:
 * adapters must either reject before mutation or return the committed receipt.
 */
export async function startLocalMcpServer({ mode = "read", invoke, onAudit = () => {}, timeoutMs = 15_000 }) {
  if (!["read", "control"].includes(mode) || typeof invoke !== "function") throw new TypeError("Invalid MCP configuration");
  const secret = randomBytes(32).toString("base64url");
  const sessions = new Map();
  const pending = new Map();
  let closing = false;
  let port = 0;
  let rateStart = Date.now();
  let rateCount = 0;

  function finish(response, status, value, headers = {}) {
    if (response.destroyed || response.writableEnded) return;
    let body = value === undefined ? "" : JSON.stringify(value);
    if (Buffer.byteLength(body) > MAX_RESULT) { status = 500; body = JSON.stringify(rpcError(null, -32603, "Result exceeds limit")); }
    response.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", ...headers });
    response.end(body);
  }

  function dropSession(id) {
    sessions.delete(id);
    for (const entry of pending.values()) if (entry.sessionId === id) entry.controller.abort();
  }

  async function dispatch(request, response, message) {
    const id = message?.id;
    const hasId = Object.hasOwn(message ?? {}, "id");
    if (!object(message) || message.jsonrpc !== "2.0" || typeof message.method !== "string"
      || (hasId && !(typeof id === "string" && id.length <= 160 || Number.isSafeInteger(id)))
      || (message.params !== undefined && !object(message.params))) {
      return finish(response, 400, rpcError(null, -32600, "Invalid JSON-RPC request"));
    }
    if (message.method === "initialize") {
      const p = message.params;
      if (!hasId || !object(p) || typeof p.protocolVersion !== "string" || !object(p.capabilities)
        || !object(p.clientInfo) || typeof p.clientInfo.name !== "string" || typeof p.clientInfo.version !== "string") {
        return finish(response, 400, rpcError(hasId ? id : null, -32602, "Invalid initialization"));
      }
      if (sessions.size >= MAX_SESSIONS) return finish(response, 429, rpcError(id, -32000, "Close an existing MCP session first"));
      const sessionId = randomBytes(24).toString("base64url");
      sessions.set(sessionId, { initialized: false, operations: new Map() });
      return finish(response, 200, rpcResult(id, {
        protocolVersion: MCP_PROTOCOL_VERSION, capabilities: { tools: { listChanged: false } },
        serverInfo: { name: "CandleScope Local Control", version: "1.0.0" },
        instructions: `Local ${mode} access. Query exact view/revision before changes. Script execution, real orders, credentials, files and unrevealed replay data are not exposed.`,
      }), { "Mcp-Session-Id": sessionId });
    }
    const sessionId = request.headers["mcp-session-id"];
    const session = sessions.get(sessionId);
    if (!session) return finish(response, sessionId ? 404 : 400, rpcError(hasId ? id : null, -32000, "MCP session required"));
    if (request.headers["mcp-protocol-version"] !== MCP_PROTOCOL_VERSION) return finish(response, 400, rpcError(hasId ? id : null, -32600, "Unsupported MCP protocol version"));
    if (!hasId) {
      if (message.method === "notifications/initialized") session.initialized = true;
      if (message.method === "notifications/cancelled") {
        const entry = pending.get(JSON.stringify([sessionId, message.params?.requestId]));
        entry?.controller.abort();
      }
      return finish(response, 202);
    }
    if (message.method === "ping") return finish(response, 200, rpcResult(id, {}));
    if (!session.initialized) return finish(response, 400, rpcError(id, -32000, "Initialization notification required"));
    if (message.method === "tools/list") {
      if (message.params?.cursor !== undefined) return finish(response, 200, rpcError(id, -32602, "Unexpected pagination cursor"));
      return finish(response, 200, rpcResult(id, { tools: MCP_TOOLS.filter((tool) => mode === "control" || tool.annotations.readOnlyHint) }));
    }
    if (message.method !== "tools/call") return finish(response, 200, rpcError(id, -32601, "Method not found"));
    const name = message.params?.name;
    const args = message.params?.arguments ?? {};
    let tool;
    try { tool = validateMcpToolCall(name, args); }
    catch (error) { return finish(response, 200, rpcError(id, -32602, error.message)); }
    if (mode !== "control" && !tool.annotations.readOnlyHint) {
      return finish(response, 200, rpcResult(id, toolResult({ code: "CONTROL_PERMISSION_REQUIRED" }, true)));
    }
    const key = stableKey(name, args);
    const operation = args.operationId && session.operations.get(args.operationId);
    if (operation) {
      if (operation.key !== key) return finish(response, 200, rpcResult(id, toolResult({ code: "OPERATION_ID_CONFLICT" }, true)));
      return finish(response, 200, rpcResult(id, await operation.result));
    }
    if (args.operationId && session.operations.size >= MAX_OPERATIONS) {
      return finish(response, 200, rpcResult(id, toolResult({ code: "SESSION_OPERATION_LIMIT", message: "Start a new session and reread the target revision." }, true)));
    }
    const pendingKey = JSON.stringify([sessionId, id]);
    if (pending.has(pendingKey) || pending.size >= 16) return finish(response, 429, rpcError(id, -32000, "Request busy"));
    const controller = new AbortController();
    const entry = { controller, sessionId };
    pending.set(pendingKey, entry);
    const startedAt = Date.now();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let stopWaiting;
    const cancelled = new Promise((resolve) => {
      stopWaiting = () => resolve(toolResult({ code: args.operationId ? "CONTROL_OUTCOME_UNKNOWN_READ_VIEW" : "CONTROL_CANCELLED" }, true));
      controller.signal.addEventListener("abort", stopWaiting, { once: true });
    });
    const invocation = Promise.resolve().then(() => {
      if (controller.signal.aborted || closing) throw new Error("REQUEST_CANCELLED");
      return invoke(name, structuredClone(args), controller.signal);
    }).then((value) => {
      if (!object(value)) throw new Error("INVALID_CONTROL_RECEIPT");
      return toolResult(value);
    }).catch((error) => toolResult({ code: error?.code ?? "CONTROL_REQUEST_FAILED", message: String(error?.message ?? "Control request failed").slice(0, 1000) }, true));
    const result = Promise.race([invocation, cancelled]).then((receipt) => {
        // Never log data, bearer/session tokens, market prices, or input payloads.
        try { onAudit({ tool: name, windowId: args.windowId ?? null, viewId: args.viewId ?? null, outcome: receipt.isError ? "error" : "complete", elapsedMs: Date.now() - startedAt }); } catch { /* Observability cannot change a committed result. */ }
        return receipt;
      }).finally(() => { clearTimeout(timer); controller.signal.removeEventListener("abort", stopWaiting); pending.delete(pendingKey); });
    if (args.operationId) session.operations.set(args.operationId, { key, result });
    return finish(response, 200, rpcResult(id, await result));
  }

  const server = http.createServer(async (request, response) => {
    try {
      if (closing || request.url !== "/mcp") return finish(response, 404);
      if (request.headers.host !== `127.0.0.1:${port}`) return finish(response, 403);
      // Native MCP clients omit Origin. Browser-origin traffic is intentionally
      // excluded; renderer management uses trusted Electron IPC instead.
      if (request.headers.origin !== undefined) return finish(response, 403);
      if (!authorized(request, secret)) return finish(response, 401, undefined, { "WWW-Authenticate": 'Bearer realm="CandleScope local MCP"' });
      if (Date.now() - rateStart >= 60_000) { rateStart = Date.now(); rateCount = 0; }
      if (++rateCount > 240) return finish(response, 429);
      if (request.method === "GET") return finish(response, 405, undefined, { Allow: "POST, DELETE" });
      if (request.method === "DELETE") {
        if (!sessions.has(request.headers["mcp-session-id"])) return finish(response, 404);
        dropSession(request.headers["mcp-session-id"]);
        return finish(response, 204);
      }
      if (request.method !== "POST") return finish(response, 405, undefined, { Allow: "POST, DELETE" });
      const accept = request.headers.accept ?? "";
      if (!accept.includes("application/json") || !accept.includes("text/event-stream")) return finish(response, 406);
      if (!request.headers["content-type"]?.split(";")[0].trim().match(/^application\/json$/i)) return finish(response, 415);
      let bytes = 0;
      const chunks = [];
      for await (const chunk of request) {
        bytes += chunk.length;
        if (bytes > MAX_BODY) return finish(response, 413);
        chunks.push(chunk);
      }
      let message;
      try { message = JSON.parse(Buffer.concat(chunks).toString("utf8")); }
      catch { return finish(response, 400, rpcError(null, -32700, "Invalid JSON")); }
      await dispatch(request, response, message);
    } catch { finish(response, 500, rpcError(null, -32603, "Local MCP request failed")); }
  });
  server.requestTimeout = 10_000;
  server.headersTimeout = 10_000;
  await new Promise((resolve, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", resolve); });
  port = server.address().port;
  return {
    endpoint: `http://127.0.0.1:${port}/mcp`, token: secret, mode,
    async close() {
      closing = true;
      for (const id of sessions.keys()) dropSession(id);
      server.closeAllConnections();
      await new Promise((resolve) => server.close(resolve));
    },
  };
}
