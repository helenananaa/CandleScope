/** Real Electron/control/MCP acceptance with an isolated profile and synthetic market HTTP data. */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { mkdir, writeFile, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { _electron as electron } from "playwright-core";
import { WebSocketServer } from "ws";
import { Client } from "@modelcontextprotocol/client";
import { StdioClientTransport } from "@modelcontextprotocol/client/stdio";
import { startDesktopAssetServer } from "../../frontend/desktop/app-origin.mjs";
import { ControlClient } from "./client.mjs";

const directory = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(directory, "../..");
const root = path.join(repo, "output", "control-desktop", new Date().toISOString().replace(/[:.]/g, "-"));
await mkdir(root, { recursive: true });
const report = { schema: "candlescope.control-desktop-smoke/1", result: "running", marketEvidence: "synthetic HTTP fixtures; no exchange connection", phases: [], errors: [], console: [] };
const save = () => writeFile(path.join(root, "report.json"), JSON.stringify(report, null, 2));
const record = async (name, evidence) => { report.phases.push({ name, evidence }); await save(); console.log(`PASS ${name}`); };
const intervals = ["1m", "5m", "15m", "1h", "4h", "1d"];
const capability = { exchange: "binance", name: "Binance fixture", markets: [{ market_type: "spot", product_type: "spot", label: "Spot" }, { market_type: "futures", product_type: "linear_perpetual", label: "Futures" }],
  native_intervals: intervals, protocol_features: [], limits: {}, known_limitations: ["synthetic acceptance data"] };
function bars(params) {
  const interval = params.get("interval") ?? "1h";
  const unit = { m: 60, h: 3600, d: 86400 }[interval.at(-1)] ?? 60;
  const seconds = Number.parseInt(interval) * unit;
  const end = Math.floor(Date.now() / 1000 / seconds) * seconds;
  const data = Array.from({ length: 800 }, (_, i) => {
    const open = 60_000 + i * 3 + Math.sin(i / 15) * 200;
    return { time: end - (800 - i) * seconds, open, high: open + 30, low: open - 25, close: open + Math.sin(i) * 20, volume: 50 + i % 30, is_closed: true };
  });
  return { data, exchange: params.get("exchange") ?? "binance", market_type: params.get("market_type") ?? "spot",
    symbol: params.get("symbol") ?? "BTCUSDT", interval, count: data.length, has_more: false,
    truncated: false, has_tail_gap: false, backfill_triggered: false, verified_contiguous: true, all_rows_final: true,
    renderable: true, complete: true, retryable: false, history_state: "ready",
    reached_latest_closed_bar: true, missing_ranges: [], source: "control-acceptance-fixture" };
}
const routes = new Set();
let importedDataset = null;
let uploadedCsv = Buffer.alloc(0);
let strategyRun = null;
let strategySubmissions = 0;
const backend = createServer(async (request, response) => {
  const url = new URL(request.url, "http://127.0.0.1"); routes.add(url.pathname);
  response.setHeader("Access-Control-Allow-Origin", "*");
  response.setHeader("Access-Control-Allow-Headers", "Content-Type, Idempotency-Key");
  if (request.method === "OPTIONS") { response.writeHead(204).end(); return; }
  let payload;
  if (url.pathname === "/api/v1/local/datasets") payload = { datasets: importedDataset ? [importedDataset] : [] };
  else if (url.pathname === "/api/v1/local/trash") payload = { entries: [] };
  else if (url.pathname === "/api/v1/local/datasets/agent-csv/revisions") payload = { revisions: [{ ...importedDataset, current: true, quality_status: "ready" }] };
  else if (url.pathname === "/api/v1/local/datasets/agent-csv/quality") payload = { manifest: importedDataset, quality: { status: "ready", rows: 800, excluded_ranges: [], duplicates: 0, out_of_order: 0, invalid_rows: 0, volume_available: true, missing_volume_rows: 0 }, receipt: {} };
  else if (url.pathname === "/api/v1/local/imports/csv/jobs") {
    const chunks = []; for await (const chunk of request) chunks.push(chunk); uploadedCsv = Buffer.concat(chunks);
    const data = bars(new URLSearchParams({ interval: "1h" })).data;
    importedDataset = { schema_version: 1, dataset_id: "agent-csv", data_epoch: "agent-csv-epoch", name: url.searchParams.get("name"), source: "local_dataset", symbol: "BTCUSDT", interval: "1h", volume_available: true, timezone: "UTC", timestamp_semantics: "bar_open", rows: data.length, first_open_ms: data[0].time * 1000, last_open_ms: data.at(-1).time * 1000, all_rows_final: true, excluded_range_count: 0, sqlite_sha256: "fixture", imported_at: new Date().toISOString() };
    payload = { job_id: "csv-job", kind: "csv_import", status: "completed", stage: "completed", processed_rows: data.length, total_rows: data.length, created_at: new Date().toISOString(), started_at: null, finished_at: null, dataset: importedDataset, error: null, cancel_requested: false };
  }
  else if (url.pathname === "/api/v1/local/projects/agent-csv/export") {
    response.writeHead(200, { "Content-Type": "application/octet-stream" }).end(Buffer.from("fixture-csproject\n")); return;
  }
  else if (url.pathname.endsWith("/indicators/compute/batch")) {
    const chunks = []; for await (const chunk of request) chunks.push(chunk);
    const input = JSON.parse(Buffer.concat(chunks).toString());
    payload = { ok: true, schemaVersion: 1, results: input.requests.map((item) => {
      let average = input.ohlcv[0]?.close ?? 0;
      const alpha = 2 / (item.params.period + 1);
      const data = input.ohlcv.map((bar) => { average = alpha * bar.close + (1 - alpha) * average; return { time: bar.time, value: average }; });
      return { clientId: item.clientId, jobKey: item.jobKey, payload: { ok: true, error: null,
        lines: [{ id: "ema", name: `EMA ${item.params.period}`, color: item.params.period === 20 ? "#f5bb46" : "#5a9fff", overlay: true, data }] } };
    }) };
  } else if (url.pathname.endsWith("/klines/history/batch")) {
    const chunks = []; for await (const chunk of request) chunks.push(chunk);
    const input = JSON.parse(Buffer.concat(chunks).toString());
    payload = { results: input.requests.map((item) => ({ request_id: item.request_id, ok: true, status: 200,
      payload: bars(new URLSearchParams(Object.entries(item).map(([key, value]) => [key, String(value)]))) })) };
  } else if (url.pathname.includes("/klines/") && !url.pathname.includes("storage")) payload = bars(url.searchParams);
  else if (url.pathname === "/api/v1/exchanges/") payload = { exchanges: [capability] };
  else if (url.pathname.endsWith("/capabilities") && url.pathname.includes("/exchanges/")) payload = capability;
  else if (url.pathname === "/api/v1/backtests/native/capabilities") payload = { engines: [{ language: "pine", available: true, external_available: false }] };
  else if (url.pathname === "/api/v1/backtests/chart-context/resolve") payload = { status: "READY", dataset_id: "fixture-dataset", data_epoch: "fixture-epoch", snapshot_hash: "fixture-snapshot",
    coverage: { available_start_ms: 1_700_000_000_000, available_end_ms: 1_700_100_000_000 } };
  else if (url.pathname === "/api/v1/backtests/native/runs") {
    if (request.method === "POST") {
      const chunks = []; for await (const chunk of request) chunks.push(chunk);
      const input = JSON.parse(Buffer.concat(chunks).toString()); strategySubmissions++;
      strategyRun = { run_id: "native-agent-fixture", state: "RUNNING", created_at_ms: Date.now(), config: { source: input.source, language: input.language, parameters: input.parameters },
        runtime_identity: { engine: { package: "acceptance-fixture", version: "0", code_sha256: "fixture" } } }; payload = strategyRun;
    } else payload = { runs: strategyRun ? [strategyRun] : [] };
  }
  else if (url.pathname === "/api/v1/backtests/native/runs/native-agent-fixture/cancel") { strategyRun = { ...strategyRun, state: "CANCELLED" }; payload = strategyRun; }
  else if (url.pathname === "/api/v1/backtests/native/runs/native-agent-fixture") payload = strategyRun;
  else if (url.pathname.includes("/presets") || url.pathname.includes("/custom") || url.pathname.includes("/alerts/rules")) payload = [];
  else { response.writeHead(404, { "Content-Type": "application/json" }).end(JSON.stringify({ detail: "Not available in fixture" })); return; }
  response.writeHead(200, { "Content-Type": "application/json" }).end(JSON.stringify(payload));
});
const streams = new WebSocketServer({ noServer: true });
backend.on("upgrade", (request, socket, head) => streams.handleUpgrade(request, socket, head, (stream) => {
  stream.send(JSON.stringify({ type: "connected" }));
  stream.on("message", (raw) => {
    if (String(raw) === "ping") { stream.send("pong"); return; }
    const command = JSON.parse(String(raw));
    for (const item of command.items ?? []) stream.send(JSON.stringify({ type: "subscription_ack", ok: true,
      client_id: item.clientId, action: command.action, active_intervals: command.action === "unsubscribe" ? [] : item.intervals, failed: [] }));
  });
}));
// Windows can allocate a low port for listen(0), including Chromium-blocked
// ports (a retained run hit 1723). Reserve fixture listeners in the high range.
const fixturePort = () => 49152 + Math.floor(Math.random() * 16000);
for (let attempt = 0; ; attempt++) {
  try {
    await new Promise((resolve, reject) => {
      backend.once("error", reject); backend.listen(fixturePort(), "127.0.0.1", () => { backend.removeListener("error", reject); resolve(); });
    }); break;
  } catch (error) { if (error.code !== "EADDRINUSE" || attempt >= 8) throw error; }
}
let assets;
for (let attempt = 0; attempt < 8; attempt++) {
  const candidate = await startDesktopAssetServer(path.join(repo, "frontend", "dist"), { port: fixturePort() });
  if (Number(new URL(candidate.appUrl).port) >= 49152) { assets = candidate; break; }
  await candidate.close();
}
if (!assets) throw new Error("Could not allocate a browser-safe asset fixture port");
let app; let mcp; let transport; let control; let page;
try {
  const env = { ...process.env, CANDLESCOPE_DESKTOP_SKIP_SIDECAR: "1", CANDLESCOPE_EXTENSIONS_SAFE_MODE: "1",
    CANDLESCOPE_DESKTOP_USER_DATA: path.join(root, "profile"), CANDLESCOPE_DESKTOP_URL: assets.appUrl,
    CANDLESCOPE_DESKTOP_BACKEND_PORT: String(backend.address().port), CANDLESCOPE_CONTROL_ENABLED: "0", CANDLESCOPE_CONTROL_EDIT: "0" };
  delete env.ELECTRON_RUN_AS_NODE;
  for (const name of ["CANDLESCOPE_DESKTOP_SPIKE_OUT", "CANDLESCOPE_DESKTOP_RESTORE_PROBE_OUT", "CANDLESCOPE_DESKTOP_PHASE7_OUT", "CANDLESCOPE_DESKTOP_PHASE8_OUT"]) delete env[name];
  const requireFrontend = createRequire(path.join(repo, "frontend", "package.json"));
  app = await electron.launch({ executablePath: requireFrontend("electron"), args: [path.join(repo, "frontend", "desktop", "main.mjs")], env, timeout: 45_000 });
  page = await app.firstWindow();
  page.on("pageerror", (error) => { report.errors.push(error.message); });
  app.context().on("page", (newPage) => newPage.on("pageerror", (error) => report.errors.push(error.message)));
  page.on("console", (message) => { if (report.console.length < 80 && ["error", "warning"].includes(message.type())) report.console.push(message.text()); });
  await page.waitForFunction(() => !!window.candlescopeDesktop?.aiControlStatus);
  assert.equal(await page.evaluate(async () => (await window.candlescopeDesktop.aiControlStatus()).mode), "off");
  await page.evaluate(() => window.candlescopeDesktop.aiControlSetMode("control", true));
  const file = path.join(root, "profile", "control", "connection.json");
  control = new ControlClient(file);
  const deadline = Date.now() + 45_000;
  let capabilities;
  while (Date.now() < deadline) {
    try { capabilities = await control.connect(); if (capabilities.windows.some((item) => item.ready)) break; } catch { /* bootstrap */ }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  assert.ok(capabilities?.windows.some((item) => item.ready), "renderer control bridge becomes ready");
  await record("native-control-bootstrap", { instanceId: capabilities.instanceId, windows: capabilities.windows });
  transport = new StdioClientTransport({ command: process.execPath, args: [path.join(directory, "cli.mjs"), "mcp", "--connection", file], stderr: "pipe" });
  mcp = new Client({ name: "desktop-acceptance", version: "1.0.0" }); await mcp.connect(transport);
  const toolCall = async (name, args) => {
    const result = await mcp.callTool({ name, arguments: args });
    assert.notEqual(result.isError, true, JSON.stringify(result.content)); return result;
  };
  let inspected;
  for (let i = 0; i < 100; i++) {
    inspected = (await toolCall("workspace_inspect", { windowId: "main-window" })).structuredContent.snapshot;
    if (inspected.ready && inspected.persistence.state === "saved") break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  assert.equal(inspected.ready, true);
  const config = { requestId: "native-four-chart", workspaceId: inspected.workspaceId, windowId: "main-window",
    expectedRevision: inspected.revision, layout: "quad", charts: ["5m", "15m", "1h", "4h"].map((interval) => ({
      session: { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval },
      indicators: [{ name: "EMA", period: 20 }, { name: "EMA", period: 60 }],
    })) };
  await toolCall("workspace_configure", config);
  let receipt;
  const completionDeadline = Date.now() + 35_000;
  while (Date.now() < completionDeadline) {
    receipt = (await toolCall("request_get", { requestId: config.requestId })).structuredContent;
    if (receipt.final) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  await writeFile(path.join(root, "configuration-receipt.json"), JSON.stringify(receipt, null, 2));
  assert.equal(receipt.state, "ready", `Readiness ${receipt.code}; see configuration-receipt.json`);
  assert.equal(receipt.revision, inspected.revision + 1);
  assert.deepEqual(receipt.snapshot.cells.map((item) => item.session.interval), ["5m", "15m", "1h", "4h"]);
  assert.equal(await page.locator("[data-chart-cell-id]").count(), 4);
  await record("mcp-four-chart-ema-ready", receipt);
  await toolCall("workspace_configure", config);
  const afterRetry = (await toolCall("workspace_inspect", { windowId: "main-window" })).structuredContent.snapshot;
  assert.equal(afterRetry.revision, receipt.revision);
  await record("idempotent-retry", { revision: afterRetry.revision });
  const stale = { ...config, requestId: "native-stale" };
  await toolCall("workspace_configure", stale);
  await new Promise((resolve) => setTimeout(resolve, 200));
  const rejected = await mcp.callTool({ name: "request_get", arguments: { requestId: stale.requestId } });
  assert.equal(rejected.structuredContent.code, "REVISION_CONFLICT");
  await record("stale-revision-rejected", rejected.structuredContent);
  const discover = async (windowId = "main-window") => (await toolCall("app_commands", { windowId })).structuredContent.groups;
  const query = async (groupId, windowId = "main-window") => (await toolCall("app_query", { windowId, groupId, command: "inspect" })).structuredContent;
  let commandSequence = 0;
  const execute = async (groupId, command, args = {}, windowId = "main-window") => {
    const group = (await discover(windowId)).find((item) => item.id === groupId); assert.ok(group, groupId);
    const requestId = `catalog-${++commandSequence}`;
    await toolCall("app_execute", { windowId, groupId, command, args, requestId, expectedContext: group.contextToken });
    for (let i = 0; i < 100; i++) {
      const result = (await toolCall("request_get", { requestId })).structuredContent;
      if (result.final) { assert.equal(result.state, "applied"); return result; }
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    throw new Error(`Command did not finish: ${groupId}.${command}`);
  };
  const groups = await discover();
  assert.ok(groups.some((group) => group.id === "workspace"));
  assert.equal(groups.filter((group) => group.id.startsWith("chart:")).length, 4);
  await record("command-catalog", groups.map((group) => ({ id: group.id, commands: group.commands.length })));
  for (const group of groups) assert.equal((await query(group.id)).state, "ready", `JSON snapshot: ${group.id}`);
  for (const group of groups.filter((item) => item.id.startsWith("plugins:"))) {
    for (const item of group.commands.filter((item) => ["app.trust", "app.live"].includes(item.requiredScope))) assert.equal(item.available, false);
  }
  await record("all-main-group-snapshots-and-privileged-scope-gates", { inspected: groups.length, trustEnabled: false, liveEnabled: false });
  const watchlist = await execute("watchlist", "create", { name: "Agent acceptance" });
  assert.ok((await query("watchlist")).snapshot.watchlists.some((item) => item.id === watchlist.output.listId));
  await execute("watchlist", "delete", { listId: watchlist.output.listId });
  await execute("settings", "appearance", { theme: "light" });
  assert.equal((await query("settings")).snapshot.settings.theme, "light");
  await execute("settings", "appearance", { theme: "dark" });
  const drawingGroupId = groups.find((group) => group.id.startsWith("drawings:")).id;
  let drawing;
  for (let i = 0; i < 100; i++) {
    drawing = (await query(drawingGroupId)).snapshot.panes.find((item) => item.paneId === "main") ?? (await query(drawingGroupId)).snapshot.panes[0];
    if (drawing) break;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  assert.ok(drawing, "canonical drawing pane is published");
  const bar = (await toolCall("app_query", { windowId: "main-window", groupId: groups.find((group) => group.id.startsWith("chart:")).id, command: "bars", args: { limit: 2 } })).structuredContent.output;
  const drawingId = "agent-acceptance-line";
  await execute(drawingGroupId, "apply", { paneId: drawing.paneId, scopeKey: drawing.scopeKey, expectedRevision: drawing.revision, commands: [{ type: "create", entity: {
    id: drawingId, kind: "line", geometry: { kind: "line", lineType: "line-segment", dataPoints: bar.map((item) => ({ time: item.time, price: item.close })) }, style: { kind: "line", color: "#ffcc00", lineWidth: 2 },
  } }] });
  assert.ok((await query(drawingGroupId)).snapshot.panes.some((pane) => pane.entities.some((entity) => entity.id === drawingId)));
  await execute(drawingGroupId, "undo", { paneId: drawing.paneId });
  assert.ok((await query(drawingGroupId)).snapshot.panes.every((pane) => !pane.entities.some((entity) => entity.id === drawingId)));
  await execute(drawingGroupId, "redo", { paneId: drawing.paneId });
  assert.ok((await query(drawingGroupId)).snapshot.panes.some((pane) => pane.entities.some((entity) => entity.id === drawingId)));
  drawing = (await query(drawingGroupId)).snapshot.panes.find((item) => item.paneId === drawing.paneId);
  await execute(drawingGroupId, "apply", { paneId: drawing.paneId, scopeKey: drawing.scopeKey, expectedRevision: drawing.revision, commands: [{ type: "delete", id: drawingId }] });
  await record("catalog-watchlist-settings-drawing-history", { drawingGroupId, revision: drawing.revision });
  const watchlistFile = (await execute("watchlist", "export")).output;
  const savedWatchlist = (await toolCall("file_read", { windowId: "main-window", fileRef: watchlistFile.fileRef, offset: 0 })).structuredContent;
  const watchlistBytes = Buffer.from(savedWatchlist.data, "base64");
  assert.equal(createHash("sha256").update(watchlistBytes).digest("hex"), watchlistFile.sha256);
  await execute("watchlist", "import", { fileRef: watchlistFile.fileRef, confirmed: true });
  await record("renderer-file-export-import-roundtrip", { fileRef: watchlistFile.fileRef, bytes: watchlistFile.size, sha256: watchlistFile.sha256 });
  const cellId = groups.find((group) => group.id.startsWith("chart:")).id.slice("chart:".length);
  await execute(`panels:${cellId}`, "show", { panel: "settings", visible: true });
  await execute(`panels:${cellId}`, "show", { panel: "indicators", visible: true });
  await execute(`panels:${cellId}`, "show", { panel: "alerts", visible: true });
  let lazyGroups;
  for (let i = 0; i < 100; i++) { lazyGroups = await discover(); if (["maintenance:", "indicator-catalog:", "alerts:"].every((prefix) => lazyGroups.some((item) => item.id.startsWith(prefix)))) break; await new Promise((resolve) => setTimeout(resolve, 100)); }
  for (const prefix of ["maintenance:", "indicator-catalog:", "alerts:"]) { const item = lazyGroups.find((item) => item.id.startsWith(prefix)); assert.ok(item, prefix); assert.equal((await query(item.id)).state, "ready"); }
  const settingsPanel = lazyGroups.find((item) => item.id.startsWith("settings-panel:"));
  await execute(settingsPanel.id, "dataWorkbench", { open: true });
  let workbench;
  for (let i = 0; i < 100; i++) { workbench = (await discover()).find((item) => item.id.startsWith("data-workbench:")); if (workbench) break; await new Promise((resolve) => setTimeout(resolve, 100)); }
  assert.ok(workbench); assert.equal((await query(workbench.id)).state, "ready");
  await execute(settingsPanel.id, "dataWorkbench", { open: false });
  for (const panel of ["settings", "indicators", "alerts"]) await execute(`panels:${cellId}`, "show", { panel, visible: false });
  await record("lazy-settings-alerts-indicator-and-workbench-discovery", { groups: lazyGroups.filter((item) => /^(maintenance|indicator-catalog|alerts|settings-panel):/.test(item.id)).map((item) => item.id) });
  const exportId = `export:${cellId}`;
  await execute(exportId, "open");
  let preview;
  for (let i = 0; i < 100; i++) { preview = (await query(exportId)).snapshot; if (preview.previewReady && !preview.busy) break; await new Promise((resolve) => setTimeout(resolve, 100)); }
  assert.equal(preview.previewReady, true, JSON.stringify(preview));
  const chartFile = (await execute(exportId, "save")).output;
  const chartParts = [];
  for (let offset = 0; offset < chartFile.size;) { const part = (await toolCall("file_read", { windowId: "main-window", fileRef: chartFile.fileRef, offset })).structuredContent; const bytes = Buffer.from(part.data, "base64"); assert.ok(bytes.length); chartParts.push(bytes); offset += bytes.length; }
  const chartBytes = Buffer.concat(chartParts); assert.equal(createHash("sha256").update(chartBytes).digest("hex"), chartFile.sha256); assert.equal(chartBytes.subarray(1, 4).toString(), "PNG");
  await execute(exportId, "close");
  await record("chart-export-preview-lease-and-download", { bytes: chartBytes.length, sha256: chartFile.sha256 });
  await execute("workspace", "setActiveCell", { cellId });
  await execute("workspace", "setStrategyTesterMode", { cellId, mode: "NATIVE" });
  await execute(`panels:${cellId}`, "show", { panel: "strategy", visible: true });
  let nativeGroup;
  for (let i = 0; i < 100; i++) {
    nativeGroup = (await discover()).find((group) => group.id.startsWith("native:"));
    if (nativeGroup) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  assert.ok(nativeGroup, "opened chart strategy dock advertises its native draft commands");
  const draftSource = '//@version=6\nstrategy("Agent acceptance")\nplot(close)\n';
  await execute(nativeGroup.id, "draft", { source: draftSource, parameters: { period: 20 } });
  assert.equal((await query(nativeGroup.id)).snapshot.source, draftSource);
  await record("mcp-native-strategy-draft", { groupId: nativeGroup.id });
  for (let i = 0; i < 100; i++) {
    nativeGroup = (await discover()).find((group) => group.id === nativeGroup.id);
    if (nativeGroup.commands.find((command) => command.name === "run").available) break;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  await execute(nativeGroup.id, "run");
  let strategyState;
  for (let i = 0; i < 100; i++) {
    strategyState = (await query(nativeGroup.id)).snapshot;
    if (strategyState.run?.state === "RUNNING") break;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  assert.equal(strategyState.run?.state, "RUNNING", strategyState.error);
  assert.equal(strategyRun.config.source, draftSource); assert.equal(strategySubmissions, 1);
  await execute(nativeGroup.id, "cancelRun");
  assert.equal((await query(nativeGroup.id)).snapshot.run.state, "CANCELLED");
  await record("mcp-strategy-run-cancel-protocol", { submissions: strategySubmissions, authority: "synthetic job lifecycle; no strategy engine execution" });
  const strategyMode = (await discover()).find((group) => group.id.startsWith("strategy-mode:")); assert.ok(strategyMode);
  await execute(strategyMode.id, "mode", { mode: "CANDLESCOPE" });
  let hostGroup;
  for (let i = 0; i < 100; i++) { hostGroup = (await discover()).find((group) => group.id.startsWith("host-chart-strategy:")); if (hostGroup) break; await new Promise((resolve) => setTimeout(resolve, 100)); }
  assert.ok(hostGroup); assert.equal((await query(hostGroup.id)).state, "ready");
  await execute(hostGroup.id, "createDraft", { name: "Agent host draft", source: "strategy(\"Agent host draft\")\nplot(close)" });
  let hostState;
  for (let i = 0; i < 100; i++) { hostState = (await query(hostGroup.id)).snapshot; if (hostState.draftId) break; await new Promise((resolve) => setTimeout(resolve, 100)); }
  assert.ok(hostState.draftId); assert.equal(hostState.source, "strategy(\"Agent host draft\")\nplot(close)");
  await record("legacy-host-draft-control", { groupId: hostGroup.id, draftId: hostState.draftId });
  await execute(strategyMode.id, "mode", { mode: "NATIVE" });
  await execute(`panels:${cellId}`, "show", { panel: "strategy", visible: false });
  await toolCall("app_open", { requestId: "open-strategy", windowId: "main-window", page: "strategy" });
  let strategyWindow;
  for (let i = 0; i < 100; i++) {
    const opened = (await toolCall("request_get", { requestId: "open-strategy" })).structuredContent;
    strategyWindow = opened.output?.windowId;
    const caps = (await toolCall("app_capabilities", {})).structuredContent;
    if (strategyWindow && caps.windows.some((window) => window.windowId === strategyWindow && window.ready)) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  assert.ok(strategyWindow);
  let researchGroups;
  for (let i = 0; i < 100; i++) {
    researchGroups = await discover(strategyWindow);
    if (researchGroups.some((group) => group.id === "research")) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  assert.ok(researchGroups.some((group) => group.id === "research"), "strategy page advertises source selection commands even without a dataset");
  assert.ok(researchGroups.some((group) => group.id === "data-library"));
  assert.equal((await query("strategy-settings", strategyWindow)).snapshot.settings.theme, "dark");
  await record("mcp-strategy-window-discovery", { windowId: strategyWindow, groups: researchGroups.map((group) => group.id) });
  await toolCall("app_open", { requestId: "open-local", windowId: "main-window", page: "local" });
  let localWindow;
  for (let i = 0; i < 100; i++) {
    localWindow = (await toolCall("request_get", { requestId: "open-local" })).structuredContent.output?.windowId;
    const caps = (await toolCall("app_capabilities", {})).structuredContent;
    if (localWindow && caps.windows.some((item) => item.windowId === localWindow && item.ready) && (await discover(localWindow)).some((item) => item.id === "data-library")) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  assert.ok(localWindow);
  const csvBytes = Buffer.from("time,open,high,low,close,volume\n" + bars(new URLSearchParams({ interval: "1h" })).data.map((bar) => [bar.time, bar.open, bar.high, bar.low, bar.close, bar.volume].join(",")).join("\n"));
  const csv = (await toolCall("file_begin", { windowId: localWindow, uploadId: "csv-desktop", name: "candles.csv", mimeType: "text/csv", size: csvBytes.length, sha256: createHash("sha256").update(csvBytes).digest("hex") })).structuredContent;
  for (let offset = 0; offset < csvBytes.length; offset += 32768) await toolCall("file_write", { windowId: localWindow, fileRef: csv.fileRef, offset, data: csvBytes.subarray(offset, offset + 32768).toString("base64") });
  await toolCall("file_commit", { windowId: localWindow, fileRef: csv.fileRef });
  const wrongWindow = await mcp.callTool({ name: "file_read", arguments: { windowId: "main-window", fileRef: csv.fileRef, offset: 0 } }); assert.equal(wrongWindow.isError, true);
  await execute("data-library", "importCsv", { fileRef: csv.fileRef, name: "Agent CSV", symbol: "BTCUSDT", interval: "1h", timezone: "UTC", timestampUnit: "s", volumeRequired: true }, localWindow);
  let library;
  for (let i = 0; i < 100; i++) { library = (await query("data-library", localWindow)).snapshot; if (!library.importing && library.datasets.some((item) => item.dataset_id === "agent-csv")) break; await new Promise((resolve) => setTimeout(resolve, 100)); }
  assert.equal(library.error, null); assert.equal(library.selectedId, "agent-csv"); assert.deepEqual(uploadedCsv, csvBytes);
  const project = (await execute("data-library", "exportProject", { datasetId: "agent-csv", clientState: { example: "chart settings" } }, localWindow)).output;
  const projectBytes = (await toolCall("file_read", { windowId: localWindow, fileRef: project.fileRef, offset: 0 })).structuredContent;
  assert.equal(Buffer.from(projectBytes.data, "base64").toString(), "fixture-csproject\n");
  await record("mcp-upload-renderer-csv-import-project-export", { windowId: localWindow, csvBytes: csvBytes.length, projectBytes: project.size, backendEvidence: "synthetic import job and project response; validates original upload/library workflow and exact transferred bytes" });
  for (const [targetPage, expectedGroup] of [["backtest", "backtest"], ["replay", "training-hub"]]) {
    const requestId = `open-${targetPage}`;
    await toolCall("app_open", { requestId, windowId: "main-window", page: targetPage });
    let targetWindow, targetGroup;
    for (let i = 0; i < 100; i++) {
      targetWindow = (await toolCall("request_get", { requestId })).structuredContent.output?.windowId;
      const caps = (await toolCall("app_capabilities", {})).structuredContent;
      if (targetWindow && caps.windows.some((window) => window.windowId === targetWindow && window.ready)) {
        targetGroup = (await discover(targetWindow)).find((group) => group.id === expectedGroup);
        if (targetGroup) break;
      }
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    assert.ok(targetGroup, `${targetPage} exposes its command group`);
    assert.equal(targetGroup.commands.find((command) => command.name === "createRun").available, false);
    const state = await query(expectedGroup, targetWindow);
    await record(`mcp-${targetPage}-window-capability-gating`, { windowId: targetWindow, phase: state.snapshot.phase,
      createRunAvailable: false, backendEvidence: "unavailable fixture backend; discovery only" });
  }
  const screenshot = await toolCall("chart_capture", { windowId: "main-window", maxSide: 1400 });
  const png = screenshot.content.find((item) => item.type === "image"); assert.ok(png);
  await writeFile(path.join(root, "four-chart.png"), Buffer.from(png.data, "base64"));
  await record("mcp-native-screenshot", { path: path.join(root, "four-chart.png"), bytes: Buffer.from(png.data, "base64").length });
  await page.reload();
  let restored;
  for (let i = 0; i < 100; i++) {
    try {
      restored = (await control.call("workspace.inspect", { windowId: "main-window" })).snapshot;
      if (restored.ready && restored.persistence.state === "saved") break;
    } catch { /* The managed renderer is reconnecting after reload. */ }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  assert.equal(restored?.layout, "quad");
  assert.deepEqual(restored.cells.map((cell) => cell.session.interval), ["5m", "15m", "1h", "4h"]);
  assert.ok(restored.cells.every((cell) => JSON.stringify(cell.indicators.map((indicator) => indicator.params.period)) === "[20,60]"));
  assert.equal(restored.persistence.mode, "indexeddb");
  await record("persisted-configuration-restores-after-reload", { revision: restored.revision, mode: restored.persistence.mode });
  const staleFile = await mcp.callTool({ name: "file_read", arguments: { windowId: "main-window", fileRef: watchlistFile.fileRef, offset: 0 } }); assert.equal(staleFile.isError, true);
  await record("window-reload-invalidates-file-handles", { staleFileRejected: true });
  assert.equal(report.errors.length, 0, JSON.stringify(report.errors));
  report.result = "pass";
} catch (error) {
  report.result = "fail"; report.failure = error.stack; process.exitCode = 1;
  try {
    const capture = await control.call("chart.capture", { windowId: "main-window" });
    await writeFile(path.join(root, "failure.png"), Buffer.from(capture.data, "base64"));
    await writeFile(path.join(root, "failure-page.txt"), await page.locator("body").ariaSnapshot());
    await writeFile(path.join(root, "performance.json"), JSON.stringify(await page.evaluate(() => window.__CANDLESCOPE_PERF__?.report()), null, 2));
    report.domReadiness = await page.locator("[data-chart-cell-id]").evaluateAll((cells) => cells.map((cell) => ({
      id: cell.getAttribute("data-chart-cell-id"), settled: cell.getAttribute("data-market-data-settled"),
      ready: cell.getAttribute("data-market-data-ready"), paused: cell.getAttribute("data-rendering-paused"),
    })));
  } catch { /* preserve the original failure */ }
  console.error(error.message);
} finally {
  await mcp?.close(); await transport?.close(); await app?.close();
  await assets.close(); for (const stream of streams.clients) stream.terminate(); streams.close();
  backend.closeAllConnections(); await new Promise((resolve) => backend.close(resolve));
  report.routes = [...routes]; await save(); console.log(`Report: ${path.join(root, "report.json")}`);
  try { await readFile(path.join(root, "profile", "control", "connection.json")); report.credentialRemovedOnExit = false; }
  catch (error) { report.credentialRemovedOnExit = error.code === "ENOENT"; }
  if (!report.credentialRemovedOnExit) { report.result = "fail"; process.exitCode = 1; }
  await save();
}
