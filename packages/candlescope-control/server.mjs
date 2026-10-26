import { McpServer } from "@modelcontextprotocol/server";
import * as z from "zod/v4";

const id = z.string().regex(/^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$/);
const session = z.object({ exchange: z.enum(["binance", "okx"]), marketType: z.enum(["spot", "futures"]),
  symbol: z.string().regex(/^[A-Z0-9][A-Z0-9_-]{0,63}$/), interval: z.string().min(2).max(16) }).strict();
const indicator = z.object({ name: z.enum(["MA", "EMA", "RSI"]), period: z.number().int().min(1).max(5000) }).strict();
const configure = z.object({ requestId: id, workspaceId: id, windowId: id, expectedRevision: z.number().int().nonnegative(),
  layout: z.enum(["single", "split-vertical", "split-horizontal", "quad"]).optional(),
  charts: z.array(z.object({ cellId: id.optional(), session, indicators: z.array(indicator).max(8) }).strict()).min(1).max(4) }).strict();

export function createControlMcp(client, capabilities) {
  const server = new McpServer({ name: "candlescope", version: "0.1.0" }, {
    instructions: "Controls the running CandleScope desktop. Use app_capabilities for window IDs and grants, app_commands for mounted command schemas and context tokens, app_query inspect for domain state, then app_execute with expectedContext. Rediscover groups after opening lazy panels or another page. The specialized workspace_configure uses workspaceId and expectedRevision, replaces indicator lists and unlinks configured cells. Keep requestId stable when retrying the same method and payload. Poll request_get until final. Generic applied receipts acknowledge execution and do not prove async jobs, disk persistence or data/indicator readiness; query domain state for those postconditions. Unknown outcome or app restart requires inspection, not blind replay. Screenshots contain visible user data.",
  });
  const register = (name, method, description, inputSchema, readOnly = true) => {
    server.registerTool(name, { description, inputSchema,
      annotations: { readOnlyHint: readOnly, destructiveHint: !readOnly, idempotentHint: true, openWorldHint: false } }, async (params) => {
      try {
        const result = await client.call(method, params);
        if (method === "chart.capture") return { content: [
          { type: "image", mimeType: result.mimeType, data: result.data },
          { type: "text", text: JSON.stringify({ windowId: result.windowId, instanceId: result.instanceId }) },
        ] };
        return { content: [{ type: "text", text: JSON.stringify(result) }], structuredContent: result,
          ...(result.state === "failed" ? { isError: true } : {}) };
      } catch (error) { return { content: [{ type: "text", text: error.message }], isError: true }; }
    });
  };
  register("app_capabilities", "app.capabilities", "List the running app instance, available windows, grants and supported configuration.", z.object({}).strict());
  register("workspace_inspect", "workspace.inspect", "Read the current document, revision, save state and chart runtime readiness in an explicit window.", z.object({ windowId: id }).strict());
  register("app_commands", "app.commands", "Discover mounted UI/domain command groups, strict JSON schemas, availability and context tokens for this window. Commands differ by page and current capabilities.", z.object({ windowId: id }).strict());
  const target = { windowId: id, groupId: z.string().min(1).max(160), command: id, args: z.record(z.string(), z.unknown()).optional() };
  register("app_query", "app.query", "Run a discovered read-only command. Use command=inspect to read a group's state. Mutating commands are rejected on this route.", z.object(target).strict());
  if (capabilities.scopes.includes("app.edit")) {
    register("app_execute", "app.execute", "Execute an available command discovered by app_commands. Bind it to the group's expectedContext token and an idempotent requestId. Poll request_get until final. An applied acknowledgement does not prove async jobs or persistence completed; inspect the domain status. Existing capability and trust checks still apply.",
      z.object({ ...target, requestId: id, expectedContext: z.string().min(1).max(160) }).strict(), false);
    register("app_open", "app.open", "Open/focus a CandleScope application page through the desktop manager. Poll the receipt for output.windowId, then discover that window's commands when ready.",
      z.object({ requestId: id, windowId: id, page: z.enum(["market", "strategy", "backtest", "replay", "local"]), search: z.string().max(2048).optional() }).strict(), false);
  }
  if (capabilities.scopes.includes("workspace.edit")) register("workspace_configure", "workspace.configure",
    "Atomically configure the current workspace window. With layout, charts follow layout order and omit cellId; otherwise cellId is required. Replaces all indicators of each configured cell and removes its link-group membership. Uses built-in local indicators only. Returns an accepted receipt; poll request_get. Layout undo does not undo indicator/session edits.", configure, false);
  register("request_get", "request.get", "Get a configuration receipt without re-executing it. final=false means still running. Receipt IDs are retained for this app session.", z.object({ requestId: id }).strict());
  const fileTarget = { windowId: id, fileRef: z.string().regex(/^[a-f0-9]{48}$/) };
  register("file_read", "file.read", "Read up to 32 KiB of a committed, window-bound file as base64. Verify size/hash when downloading. Files expire after 30 minutes idle or window reload/close.", z.object({ ...fileTarget, offset: z.number().int().nonnegative() }).strict());
  if (capabilities.scopes.includes("app.edit")) {
    register("file_begin", "file.begin", "Stage a file for a UI import or plugin installation. Max 32 MiB/file, 128 MiB/session. Use a stable uploadId for retries; no host paths. Write sequential chunks then commit its SHA-256 before using fileRef.", z.object({ windowId: id, uploadId: id, name: z.string().min(1).max(160), mimeType: z.string().max(128), size: z.number().int().min(0).max(33554432), sha256: z.string().regex(/^[a-f0-9]{64}$/) }).strict(), false);
    register("file_write", "file.write", "Write a base64 chunk (up to 32 KiB decoded) at the expected byte offset. Identical chunk retries are accepted; different bytes/offsets are rejected.", z.object({ ...fileTarget, offset: z.number().int().nonnegative(), data: z.string().max(43692) }).strict(), false);
    register("file_commit", "file.commit", "Validate full length and SHA-256 and make a staged file available to domain commands.", z.object(fileTarget).strict(), false);
    register("file_remove", "file.remove", "Release a staged/exported file from the current process.", z.object(fileTarget).strict(), false);
  }
  register("chart_capture", "chart.capture", "Capture the visible application content in a specific chart window as PNG, including chart layout and controls.", z.object({ windowId: id, maxSide: z.number().int().min(64).max(1600).optional() }).strict());
  return server;
}
