/** MCP -> production renderer -> real local-data/native/replay services.
 * Deterministic input rows; no business HTTP response stubs or real exchange orders.
 * The existing replay bootstrap seeds isolated storage and blocks external networking.
 */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { createRequire } from "node:module";
import { existsSync } from "node:fs";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { _electron as electron } from "playwright-core";
import { Client } from "@modelcontextprotocol/client";
import { StdioClientTransport } from "@modelcontextprotocol/client/stdio";
import { startDesktopAssetServer } from "../../frontend/desktop/app-origin.mjs";

const directory = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(directory, "../..");
const root = path.join(repo, "output/control-real-backend", new Date().toISOString().replace(/[:.]/g, "-"));
await mkdir(root, { recursive: true });
const report = { schema: "candlescope.control-real-backend/1", result: "running", phases: [], errors: [],
  boundary: "Production business services with deterministic local rows; isolated profile/databases; no live orders, trust grants or user-data cleanup.",
  bootstrap: "scripts.replay_smoke_fixture: seeds market archives, loopback network guard, offline metadata and disabled gap maintenance; business endpoints unmodified." };
const save = () => writeFile(path.join(root, "report.json"), JSON.stringify(report, null, 2));
const sha = (value) => createHash("sha256").update(value).digest("hex");
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const record = async (name, evidence) => { report.phases.push({ name, evidence }); await save(); console.log(`PASS ${name}`); };
async function waitFor(name, operation, accept, timeout = 45_000) {
  let last;
  const until = Date.now() + timeout;
  while (Date.now() < until) {
    try { last = await operation(); }
    catch (error) {
      // A managed page temporarily leaves the bridge during full navigation.
      // Retry only this transport state; domain and permission failures remain fatal.
      if (!String(error.message).includes("WINDOW_UNAVAILABLE")) throw error;
      await delay(100); continue;
    }
    if (accept(last)) return last;
    await delay(100);
  }
  await writeFile(path.join(root, "last-wait.json"), JSON.stringify({ name, last }, null, 2));
  throw new Error(`Timed out: ${name}; see last-wait.json`);
}
async function reservePort() {
  for (let n = 0; n < 20; n++) {
    const server = createServer();
    try {
      await new Promise((resolve, reject) => { server.once("error", reject); server.listen(49152 + Math.floor(Math.random() * 15000), "127.0.0.1", resolve); });
      const port = server.address().port;
      await new Promise((resolve) => server.close(resolve));
      return port;
    } catch (error) { if (error.code !== "EADDRINUSE") throw error; }
  }
  throw new Error("No free high port");
}
let backend, assets, app, mcp, transport;
let backendLog = "";
const windows = new Map();
try {
  const venvPython = path.join(repo, "backend/.venv/Scripts/python.exe");
  const bundledRuntime = path.join(repo, "frontend/.desktop-runtime/runtime");
  const bundledPython = path.join(bundledRuntime, "python/python.exe");
  const python = process.env.CANDLESCOPE_QA_PYTHON ?? (existsSync(venvPython) ? venvPython : existsSync(bundledPython) ? bundledPython : "python");
  const nativeRegistrySource = process.env.CANDLESCOPE_QA_NATIVE_REGISTRY ?? path.join(process.env.LOCALAPPDATA, "CandleScope/plugins/native-strategy-registry.json");
  const nativeRegistryBytes = await readFile(nativeRegistrySource);
  await writeFile(path.join(root, "native-registry.json"), nativeRegistryBytes);
  await writeFile(path.join(root, "runtime-registry.json"), JSON.stringify({ schemaVersion: 1, plugins: [] }));
  report.nativeRegistrySha256 = sha(nativeRegistryBytes);
  const backendPort = await reservePort();
  const backendOrigin = `http://127.0.0.1:${backendPort}`;
  assets = await startDesktopAssetServer(path.join(repo, "frontend/dist"), { port: await reservePort() });
  const dataRoot = path.join(root, "data");
  const env = { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8", PYTHONDONTWRITEBYTECODE: "1",
    PYTHONPATH: [...(python === bundledPython ? [path.join(bundledRuntime, "site-packages")] : []), ...["candlescope-plugin-sdk", "candlescope-backtest-sdk"].map((p) => path.join(repo, "packages", p, "src"))].join(path.delimiter),
    CANDLE_DATA_DIR: dataRoot, CANDLESCOPE_LOCAL_DATA_DIR: path.join(dataRoot, "local-data"), CORS_ORIGINS: new URL(assets.appUrl).origin,
    KLINES_DB_PATH: path.join(dataRoot, "candlescope.db"), REPLAY_DB_PATH: path.join(dataRoot, "replay.db"), BACKTEST_DB_PATH: path.join(dataRoot, "backtest.db"),
    TRADE_FLOW_DB_PATH: path.join(dataRoot, "candlescope.db"), LIQUIDATION_DB_PATH: path.join(dataRoot, "candlescope.db"),
    REPLAY_HISTORY_ARCHIVE_DIR: path.join(dataRoot, "replay-history"), REPLAY_AGG_TRADE_ARCHIVE_DIR: path.join(dataRoot, "replay-agg-trades"),
    REPLAY_ACCOUNT_HISTORY_ARCHIVE_DIR: path.join(dataRoot, "account-history"), REPLAY_HISTORICAL_BOOK_ARCHIVE_DIR: path.join(dataRoot, "historical-book"),
    HISTORY_ARCHIVE_CACHE_DIR: path.join(dataRoot, "history-cache"), RAW_AGG_TRADE_ARCHIVE_DIR: path.join(dataRoot, "raw-trades"),
    CANDLESCOPE_RUNTIME_MODE: "LIVE", REPLAY_ENABLED: "1", BACKTEST_ENABLED: "1", RESEARCH_DATA_LIBRARY_ENABLED: "1",
    REPLAY_SEGMENT_DOWNLOAD_WORKER_ENABLED: "0", REPLAY_SEGMENT_AUTO_GC_ENABLED: "0", RAW_AGG_TRADE_ARCHIVE_ENABLED: "0", AUTO_HISTORY_PREPARATION_ENABLED: "0",
    CANDLESCOPE_EXTENSIONS_SAFE_MODE: "1", CANDLESCOPE_PLUGIN_HOST_ENABLED: "1", CANDLESCOPE_OFFICIAL_PLUGIN_BOOTSTRAP: "0",
    CANDLESCOPE_RUNTIME_REGISTRY: path.join(root, "runtime-registry.json"), CANDLESCOPE_NATIVE_RUNTIME_REGISTRY: path.join(root, "native-registry.json"),
    CANDLESCOPE_PLUGIN_PLATFORM_V2_ROOT: path.join(dataRoot, "plugins"), CANDLESCOPE_PLUGIN_PLATFORM_V2_ENABLED: "0",
    BINANCE_BASE_URL: "http://127.0.0.1:9", BINANCE_WS_URL: "ws://127.0.0.1:9", BINANCE_FUTURES_BASE_URL: "http://127.0.0.1:9", BINANCE_FUTURES_WS_URL: "ws://127.0.0.1:9",
    REQUEST_TIMEOUT: "1", MAX_RETRIES: "0" };
  backend = spawn(python, ["-m", "scripts.replay_smoke_fixture", "--port", String(backendPort), "--disable-gap-maintenance"], { cwd: path.join(repo, "backend"), env, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  backend.on("error", (error) => { backendLog += error.stack; });
  for (const stream of [backend.stdout, backend.stderr]) stream.on("data", (chunk) => { backendLog += chunk; });
  const api = async (route) => { const response = await fetch(`${backendOrigin}${route}`, { signal: AbortSignal.timeout(15_000) }); assert.equal(response.ok, true, `${route}: ${response.status} ${response.ok ? "" : await response.text()}`); return response.json(); };
  await waitFor("backend startup", async () => {
    if (backend.exitCode !== null) throw new Error(`Backend exited ${backend.exitCode}; ${backendLog.slice(-3000)}`);
    try { return await api("/__replay_smoke__/fixture"); } catch { return null; }
  }, (value) => value?.network_guard?.installed === true);
  const fixture = await api("/__replay_smoke__/fixture");
  const capabilities = await api("/api/v1/backtests/native/capabilities");
  assert.ok(capabilities.engines.some((engine) => engine.available), JSON.stringify(capabilities));
  await record("real-backend-bootstrap", { fixture, nativeCapabilities: capabilities });
  report.frontendIndexSha256 = sha(await readFile(path.join(repo, "frontend/dist/index.html")));
  const dist = path.join(repo, "frontend/dist");
  report.frontendFiles = await Promise.all((await readdir(dist, { recursive: true, withFileTypes: true }))
    .filter((entry) => entry.isFile()).map(async (entry) => {
      const filename = path.join(entry.parentPath, entry.name);
      return { path: path.relative(dist, filename).replaceAll("\\", "/"), sha256: sha(await readFile(filename)) };
    }));
  report.frontendFiles.sort((a, b) => a.path.localeCompare(b.path));
  report.frontendArtifactSha256 = sha(JSON.stringify(report.frontendFiles));
  const electronEnv = { ...process.env, CANDLESCOPE_DESKTOP_SKIP_SIDECAR: "1", CANDLESCOPE_EXTENSIONS_SAFE_MODE: "1",
    CANDLESCOPE_DESKTOP_USER_DATA: path.join(root, "profile"), CANDLESCOPE_DESKTOP_URL: assets.appUrl,
    CANDLESCOPE_DESKTOP_BACKEND_PORT: String(backendPort), CANDLESCOPE_CONTROL_ENABLED: "0", CANDLESCOPE_CONTROL_EDIT: "0",
    CANDLESCOPE_CONTROL_TRUST: "0", CANDLESCOPE_CONTROL_LIVE: "0" };
  delete electronEnv.ELECTRON_RUN_AS_NODE;
  for (const key of ["CANDLESCOPE_DESKTOP_SPIKE_OUT", "CANDLESCOPE_DESKTOP_RESTORE_PROBE_OUT", "CANDLESCOPE_DESKTOP_PHASE7_OUT", "CANDLESCOPE_DESKTOP_PHASE8_OUT"]) delete electronEnv[key];
  app = await electron.launch({ executablePath: createRequire(path.join(repo, "frontend/package.json"))("electron"), args: [path.join(repo, "frontend/desktop/main.mjs")], env: electronEnv, timeout: 45_000 });
  const main = await app.firstWindow(); windows.set("main-window", main);
  for (const page of app.windows()) page.on("pageerror", (error) => report.errors.push(error.message));
  app.context().on("page", (page) => page.on("pageerror", (error) => report.errors.push(error.message)));
  report.console = []; report.httpFailures = [];
  const observe = (page) => {
    page.on("console", (message) => { if (["error", "warning"].includes(message.type()) && report.console.length < 50) report.console.push(message.text()); });
    page.on("requestfailed", (request) => { if (report.httpFailures.length < 50) report.httpFailures.push({ url: request.url(), error: request.failure() }); });
  };
  for (const page of app.windows()) observe(page);
  app.context().on("page", observe);
  await main.waitForFunction(() => !!window.candlescopeDesktop?.aiControlStatus);
  assert.equal(await main.evaluate(async () => (await window.candlescopeDesktop.aiControlStatus()).mode), "off");
  await main.evaluate(() => window.candlescopeDesktop.aiControlSetMode("control", true));
  transport = new StdioClientTransport({ command: process.execPath, args: [path.join(directory, "cli.mjs"), "mcp", "--connection", path.join(root, "profile/control/connection.json")], stderr: "pipe" });
  mcp = new Client({ name: "real-backend-acceptance", version: "1.0.0" });
  await mcp.connect(transport);
  const tool = async (name, arguments_) => {
    const result = await mcp.callTool({ name, arguments: arguments_ });
    assert.notEqual(result.isError, true, `${name}: ${JSON.stringify(result.content)}`);
    return result.structuredContent;
  };
  const discover = async (windowId) => (await tool("app_commands", { windowId })).groups;
  const query = async (windowId, groupId, command = "inspect", args = {}) => (await tool("app_query", { windowId, groupId, command, args }));
  const snapshot = async (windowId, groupId) => (await query(windowId, groupId)).snapshot;
  let sequence = 0;
  const execute = async (windowId, groupId, command, args = {}) => {
    const group = (await discover(windowId)).find((row) => row.id === groupId);
    assert.ok(group, `${windowId}.${groupId}`);
    const requestId = `real-${++sequence}`;
    await tool("app_execute", { windowId, groupId, command, args, requestId, expectedContext: group.contextToken });
    return waitFor(`${groupId}.${command} acknowledgement`, () => tool("request_get", { requestId }), (receipt) => {
      if (!receipt.final) return false;
      assert.equal(receipt.state, "applied", JSON.stringify(receipt)); return true;
    });
  };
  const matches = (id, prefix) => prefix.endsWith(":") ? id.startsWith(prefix) : id === prefix;
  const group = (windowId, prefix) => waitFor(`group ${prefix}`, () => discover(windowId), (groups) => groups.some((row) => matches(row.id, prefix))).then((groups) => groups.find((row) => matches(row.id, prefix)));
  const open = async (target) => {
    const requestId = `open-${target}`;
    await tool("app_open", { windowId: "main-window", requestId, page: target });
    const receipt = await waitFor(`open ${target}`, () => tool("request_get", { requestId }), (row) => row.final);
    assert.equal(receipt.state, "applied", JSON.stringify(receipt));
    const windowId = receipt.output.windowId;
    await waitFor(`${target} ready`, () => tool("app_capabilities", {}), (caps) => caps.windows.some((row) => row.windowId === windowId && row.ready));
    return windowId;
  };
  const upload = async (windowId, name, bytes) => {
    const file = await tool("file_begin", { windowId, uploadId: `file-${++sequence}`, name, mimeType: "application/octet-stream", size: bytes.length, sha256: sha(bytes) });
    for (let offset = 0; offset < bytes.length; offset += 32768) await tool("file_write", { windowId, fileRef: file.fileRef, offset, data: bytes.subarray(offset, offset + 32768).toString("base64") });
    return tool("file_commit", { windowId, fileRef: file.fileRef });
  };
  const download = async (windowId, file, name) => {
    const parts = [];
    for (let offset = 0; offset < file.size; offset += 32768) parts.push(Buffer.from((await tool("file_read", { windowId, fileRef: file.fileRef, offset })).data, "base64"));
    const bytes = Buffer.concat(parts); assert.equal(bytes.length, file.size); assert.equal(sha(bytes), file.sha256);
    await writeFile(path.join(root, name), bytes); return bytes;
  };
  await waitFor("main control", () => tool("app_capabilities", {}), (caps) => caps.windows.some((row) => row.ready));
  const research = await open("local");
  await group(research, "data-library");
  const startSeconds = fixture.fixture_start_ms / 1000;
  const expectedBars = Array.from({ length: 800 }, (_, index) => {
    const open = Number((30000 + 100 * Math.sin(index / 12) + index / 10).toFixed(6));
    return { time: startSeconds + index * 60, open, high: open + 20, low: open - 20, close: Number((open + (index % 2 ? -3 : 4)).toFixed(6)), volume: 10 + index % 7 };
  });
  const csv = Buffer.from("time,open,high,low,close,volume\n" + expectedBars.map((row) => Object.values(row).join(",")).join("\n"));
  await writeFile(path.join(root, "input.csv"), csv);
  const file = await upload(research, "input.csv", csv);
  await execute(research, "data-library", "importCsv", { fileRef: file.fileRef, name: "MCP real backend CSV", symbol: "BTCUSDT", interval: "1m", timezone: "UTC", timestampUnit: "s", volumeRequired: true });
  const imported = await waitFor("CSV import completion", () => snapshot(research, "data-library"), (row) => {
    if (row.error) throw new Error(row.error);
    return !row.importing && row.datasets.length === 1;
  });
  const dataset = imported.datasets[0];
  const importJobs = await api("/api/v1/local/imports/jobs");
  assert.ok(importJobs.jobs.some((job) => job.status === "completed" && job.dataset?.dataset_id === dataset.dataset_id));
  assert.equal(dataset.rows, expectedBars.length);
  const rows = await api(`/api/v1/local/datasets/${dataset.dataset_id}/klines/history?interval=1m&count_back=1000`);
  for (let index = 0; index < expectedBars.length; index++) for (const key of Object.keys(expectedBars[index])) assert.equal(rows.data[index][key], expectedBars[index][key], `bar ${index}.${key}`);
  const quality = await api(`/api/v1/local/datasets/${dataset.dataset_id}/quality?data_epoch=${encodeURIComponent(dataset.data_epoch)}`);
  await record("mcp-csv-real-import-byte-and-row-verification", { csvSha256: sha(csv), dataset, quality, importJobs, allRowsCompared: expectedBars.length });
  await execute(research, "research", "selectDataset", { datasetId: dataset.dataset_id });
  const chart = await group(research, "chart:");
  await execute(research, chart.id, "addIndicator", { id: "agent-real-ema", name: "EMA", kind: "builtin", params: { period: 20 }, visible: true });
  const chartState = await waitFor("real indicator output", () => snapshot(research, chart.id), (row) => !row.computing && row.indicators.some((indicator) => indicator.id === "agent-real-ema" && indicator.outputPointCount > 0));
  await record("mcp-imported-chart-real-indicator", chartState);
  const drawingGroup = await group(research, "drawings:");
  const drawing = await waitFor("imported drawing pane", () => snapshot(research, drawingGroup.id), (row) => row.panes.length > 0);
  const pane = drawing.panes[0];
  const drawingId = "mcp-project-line";
  await execute(research, drawingGroup.id, "apply", { paneId: pane.paneId, scopeKey: pane.scopeKey, expectedRevision: pane.revision, commands: [{ type: "create", entity: {
    id: drawingId, kind: "line", geometry: { kind: "line", lineType: "line-segment", dataPoints: [100, 200].map((index) => ({ time: expectedBars[index].time, price: expectedBars[index].close })) }, style: { kind: "line", color: "#ffcc00", lineWidth: 2 },
  } }] });
  await group(research, "local-analysis");
  const event = (await execute(research, "local-analysis", "create", { time: expectedBars[100].time, price: expectedBars[100].close, kind: "note", label: "MCP roundtrip", note: "Real backend project acceptance", color: "#ffaa00" })).output;
  await execute(research, "strategy-settings", "appearance", { theme: "light" });
  await execute(research, "research", "library", { visible: true });
  const management = await group(research, "dataset-management:");
  const project = (await execute(research, management.id, "exportProject")).output;
  const projectBytes = await download(research, project, "roundtrip.csproject");
  assert.equal(projectBytes.subarray(0, 2).toString(), "PK");
  await execute(research, "local-analysis", "delete", { eventId: event.id });
  await execute(research, chart.id, "removeIndicator", { indicatorId: "agent-real-ema" });
  const drawingPreparation = await execute(research, drawingGroup.id, "prepare", { paneId: pane.paneId });
  await record("drawing-scope-recovery-request", { output: drawingPreparation.output, snapshot: await snapshot(research, drawingGroup.id) });
  const changedPane = (await waitFor("drawing ready after indicator removal", () => snapshot(research, drawingGroup.id), (row) => row.panes[0]?.ready)).panes[0];
  await execute(research, drawingGroup.id, "apply", { paneId: changedPane.paneId, scopeKey: changedPane.scopeKey, expectedRevision: changedPane.revision, commands: [{ type: "delete", id: drawingId }] });
  await execute(research, "strategy-settings", "appearance", { theme: "dark" });
  await execute(research, management.id, "importProject", { fileRef: project.fileRef });
  const restoredLibrary = await snapshot(research, "data-library");
  assert.equal(restoredLibrary.error, null, restoredLibrary.error);
  const restored = restoredLibrary.datasets.find((row) => row.dataset_id === restoredLibrary.selectedId);
  assert.ok(restored);
  await execute(research, "research", "selectDataset", { datasetId: restored.dataset_id });
  const restoredChart = await group(research, "chart:");
  await waitFor("restored indicators", () => snapshot(research, restoredChart.id), (row) => row.indicators.some((indicator) => indicator.id === "agent-real-ema"));
  const restoredDrawing = await group(research, "drawings:");
  await waitFor("restored drawings", () => snapshot(research, restoredDrawing.id), (row) => row.panes.some((item) => item.entities.some((entity) => entity.id === drawingId)));
  const events = (await query(research, "local-analysis", "events", { offset: 0, limit: 100 })).output;
  assert.ok(events.some((row) => row.label === "MCP roundtrip"));
  assert.equal((await snapshot(research, "strategy-settings")).settings.theme, "light");
  const restoredRows = await api(`/api/v1/local/datasets/${restored.dataset_id}/klines/history?interval=1m&count_back=1000`);
  assert.deepEqual(restoredRows.data, rows.data);
  await record("mcp-project-real-export-restore", { sourceDataset: dataset.dataset_id, restoredDataset: restored.dataset_id, projectSha256: sha(projectBytes), rowsCompared: rows.data.length, events, settingsRestored: "light", indicatorsRestored: ["agent-real-ema"], drawingsRestored: [drawingId] });
  await execute(research, "research", "library", { visible: false });
  const native = await group(research, "native:");
  const nativeReady = () => waitFor("native run availability", () => discover(research), (groups) => groups.find((row) => row.id === native.id)?.commands.find((row) => row.name === "run")?.available);
  const language = capabilities.engines.find((engine) => engine.language === "pyne" && engine.available)?.language ?? capabilities.engines.find((engine) => engine.available).language;
  await execute(research, native.id, "language", { language });
  const source = language === "pyne" ? 'strategy("MCP acceptance", initial_capital=10000)\nfast = ta.sma(close, 3)\nslow = ta.sma(close, 10)\nstrategy.entry_when(ta.crossover(fast, slow), "L", strategy.long, qty=0.01)\nstrategy.close_when(ta.crossunder(fast, slow), "L")\nplot(fast, "Fast")\n' : '//@version=6\nstrategy("MCP acceptance", initial_capital=10000)\nfast = ta.sma(close, 3)\nslow = ta.sma(close, 10)\nif ta.crossover(fast, slow)\n    strategy.entry("L", strategy.long, qty=0.01)\nif ta.crossunder(fast, slow)\n    strategy.close("L")\nplot(fast)\n';
  await execute(research, native.id, "draft", { source, parameters: {} });
  await nativeReady();
  await execute(research, native.id, "run");
  const runState = await waitFor("real native strategy result", () => snapshot(research, native.id), (row) => {
    if (row.error || row.run?.state === "FAILED") throw new Error(JSON.stringify(row));
    return row.run?.state === "COMPLETED";
  }, 120_000);
  const run = await api(`/api/v1/backtests/native/runs/${runState.run.runId}`);
  assert.equal(run.config.source, source); assert.ok(run.result.trades.length > 0); assert.ok(run.result.orders.length > 0);
  const runFile = (await execute(research, native.id, "exportReport")).output;
  const exportedRun = JSON.parse(await download(research, runFile, "native-report.json"));
  assert.deepEqual(exportedRun, run);
  await record("mcp-real-native-engine-run-and-report", { runId: run.run_id, state: run.state, runtimeIdentity: run.runtime_identity, reportHash: run.result.report_hash, trades: run.result.trades.length, orders: run.result.orders.length, bars: run.result.bars.length });
  // Cancel a second actual engine job; retain the observed terminal state instead of treating an ack as proof.
  await nativeReady();
  await execute(research, native.id, "run");
  const cancelling = await waitFor("second run exists", () => snapshot(research, native.id), (row) => row.run && row.run.runId !== run.run_id);
  assert.ok(!["COMPLETED", "FAILED"].includes(cancelling.run.state), "cancel must reach an in-flight job");
  await execute(research, native.id, "cancelRun");
  const cancelled = await waitFor("cancel terminal", () => snapshot(research, native.id), (row) => row.run?.state === "CANCELLED");
  assert.equal((await api(`/api/v1/backtests/native/runs/${cancelled.run.runId}`)).state, "CANCELLED");
  await record("mcp-real-native-engine-cancellation", cancelled.run);
  const replay = await open("replay");
  await group(replay, "training-hub");
  await execute(replay, "training-hub", "openCreate");
  await waitFor("training draft", () => snapshot(replay, "training-hub"), (row) => !!row.draft && !row.operation);
  await execute(replay, "training-hub", "draft", { name: "MCP real training", sourceKind: "BAR", exchange: "binance", marketType: "spot", symbol: "BTCUSDT", baseInterval: "1m", displayInterval: "1m", requestedStartMs: fixture.fixture_start_ms + 300 * 60_000, indicatorWarmupBars: 200, forwardCacheMs: 86_400_000, integrityMode: "SANDBOX", timeDisclosurePolicy: "NONE" });
  await execute(replay, "training-hub", "refreshCreatePlan");
  await waitFor("training evaluation", () => snapshot(replay, "training-hub"), (row) => {
    if (row.error) throw new Error(row.error); return row.evaluation?.canSubmit && !row.operation;
  });
  await execute(replay, "training-hub", "createRun");
  // Creation navigates the same managed window. Observe the new authoritative group.
  await group(replay, "replay-initial-market");
  const picker = await waitFor("initial market catalog", () => snapshot(replay, "replay-initial-market"), (row) => {
    if (row.error) throw new Error(row.error); return !!row.catalog && !row.selecting;
  });
  const market = picker.catalog.entries.find((entry) => entry.identity.exchange === "binance"
    && entry.identity.market_type === "spot" && entry.identity.symbol === "BTCUSDT"
    && entry.selected_base_interval !== null && entry.start_compatibility?.state === "READY");
  assert.ok(market, "Prepared spot market must be available");
  await execute(replay, "replay-initial-market", "select", { marketKey: `${market.identity.exchange}:${market.identity.market_type}:${market.identity.symbol}` });
  await group(replay, "replay");
  const replayState = await waitFor("replay viewer", () => snapshot(replay, "replay"), (row) => !!row.viewer && !row.loading);
  const training = { run_id: replayState.runId };
  await record("mcp-real-training-create-and-viewer", { runId: training.run_id, state: await snapshot(replay, "replay") });
  await execute(replay, "replay", "control", { type: "acquire_controller", payload: { takeover: false } });
  await execute(replay, "replay", "control", { type: "step_base", payload: { count: 1 } });
  const order = { client_order_id: "mcp-training-buy", side: "BUY", order_type: "MARKET", quantity: "0.01", reduce_only: false, limit_price: null, stop_price: null };
  await execute(replay, "replay", "trade", { type: "place_order", payload: order });
  await execute(replay, "replay", "control", { type: "advance", payload: { basis: "VIRTUAL_TIME", duration_ms: 10 * 60_000 } });
  await execute(replay, "replay", "trade", { type: "place_order", payload: { ...order, client_order_id: "mcp-training-sell", side: "SELL", reduce_only: true } });
  await execute(replay, "replay", "control", { type: "step_base", payload: { count: 1 } });
  await execute(replay, "replay", "control", { type: "end", payload: { open_order_disposition: "cancel", position_disposition: "mark_close" } });
  const accountAudit = (await query(replay, "replay", "auditAccount")).output;
  assert.equal(accountAudit.status, "PASS", JSON.stringify(accountAudit));
  await group(replay, "replay-integrity");
  await execute(replay, "replay-integrity", "refresh");
  await waitFor("training report", () => snapshot(replay, "replay-integrity"), (row) => row.reportAvailable && !row.operation);
  const replayFile = (await execute(replay, "replay-integrity", "exportReport", { format: "json" })).output;
  const replayReport = JSON.parse(await download(replay, replayFile, "training-report.json"));
  const authorityReport = await api(`/api/v1/replay/runs/${training.run_id}/report`);
  assert.equal(replayReport.run_id, training.run_id);
  assert.deepEqual(replayReport.report, authorityReport.report);
  assert.ok(replayReport.report.trade_count > 0);
  assert.equal(replayReport.report.ended, true);
  assert.equal(replayReport.report.order_count, 2);
  assert.equal(replayReport.report.fill_count, 2);
  assert.deepEqual(replayReport.modelled_account, authorityReport.modelled_account);
  assert.equal(replayReport.modelled_account.ledger.reconciliation_delta, "0");
  // Approximate ONE_WAY reports omit the optional historical-exact/hedge audit.
  // The explicit MCP account-audit query above verifies the actual ledger separately.
  assert.deepEqual(replayReport.account_audit, authorityReport.account_audit);
  await record("mcp-real-training-orders-end-and-report", { runId: training.run_id, accountAudit, viewer: await snapshot(replay, "replay"), report: replayReport });
  assert.equal(report.errors.length, 0, JSON.stringify(report.errors));
  report.result = "pass";
} catch (error) {
  report.result = "fail"; report.failure = error.stack; process.exitCode = 1; console.error(error.stack);
} finally {
  if (app) {
    for (let index = 0; index < app.windows().length; index++) {
      try { const page = app.windows()[index]; await page.screenshot({ path: path.join(root, `window-${index}.png`) }); await writeFile(path.join(root, `window-${index}.html`), await page.content()); } catch { /* preserve failure */ }
    }
  }
  await mcp?.close(); await transport?.close(); await app?.close(); await assets?.close();
  if (backend && backend.exitCode === null) {
    try { await fetch(`http://127.0.0.1:${backend.spawnargs[backend.spawnargs.indexOf("--port") + 1]}/__replay_smoke__/shutdown`, { method: "POST", signal: AbortSignal.timeout(5000) }); } catch { /* forced reap below */ }
    for (let n = 0; n < 100 && backend.exitCode === null; n++) await delay(100);
    if (backend.exitCode === null) backend.kill();
    for (let n = 0; n < 50 && backend.exitCode === null; n++) await delay(100);
    report.backendExitCode = backend.exitCode;
  }
  await writeFile(path.join(root, "backend.log"), backendLog);
  try { await readFile(path.join(root, "profile/control/connection.json")); report.credentialRemovedOnExit = false; }
  catch (error) { report.credentialRemovedOnExit = error.code === "ENOENT"; }
  if (report.result === "pass" && (report.backendExitCode !== 0 || !report.credentialRemovedOnExit)) { report.result = "fail"; report.failure = "Cleanup postconditions failed"; process.exitCode = 1; }
  await save(); console.log(`Report: ${path.join(root, "report.json")}`);
}
