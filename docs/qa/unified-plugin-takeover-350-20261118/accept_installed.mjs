import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { spawn, execFileSync } from "node:child_process";
import { openSync, closeSync, existsSync, mkdtempSync, mkdirSync, readFileSync, writeFileSync, cpSync } from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { setTimeout as pause } from "node:timers/promises";

const [repo, executable, python, receiptPath] = process.argv.slice(2);
const evidence = mkdtempSync(path.join(os.tmpdir(), "candlescope-takeover-native-"));
console.log("Evidence directory", evidence);
const store = path.join(evidence, "plugins", "unified");
const plugin = "example.startup-takeover";
const cli = (...args) => JSON.parse(execFileSync(python, [
  path.join(repo, "backend/scripts/unified_plugin.py"), ...args,
], { encoding: "utf8" })).result;
const stage = (source, label) => {
  const archive = path.join(evidence, label + ".cspkg");
  cli("build", source, archive);
  return cli("stage", "--root", store, archive);
};
function approve(review) {
  const current = cli("list", "--root", store);
  return cli("activate", "--root", store, review.packageSha256,
    "--expected-revision", String(current.revision), "--approve", "full-trust:" + review.packageSha256);
}
const source = path.join(repo, "examples/unified-plugins/startup-takeover");
const good = stage(source, "good");
approve(good);
const privateRoot = path.join(store, "private", plugin);
mkdirSync(privateRoot, { recursive: true });
const fixtureFile = path.join(privateRoot, "saved.pine");
writeFileSync(fixtureFile, "// persisted fixture\n");
const fingerprint = (file) => createHash("sha256").update(readFileSync(file)).digest("hex");
const before = fingerprint(fixtureFile);
const resources = path.join(path.dirname(executable),
  process.platform === "win32" ? "resources" : "../Resources");
const receipt = {platform: process.platform, arch: process.arch, evidence,
  asarSha256: fingerprint(path.join(resources, "app.asar")),
  good: good.packageSha256, before, phases: []};
const profile = path.join(evidence, "profile");
const wait = async (label, work, timeout = 90000) => {
  const end = Date.now() + timeout;
  let reason;
  while (Date.now() < end) {
    try { const result = await work(); if (result) return result; }
    catch (error) { reason = error; }
    await pause(150);
  }
  throw new Error(label + " timed out", { cause: reason });
};
async function freePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => server.once("error", reject).listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  await new Promise((resolve) => server.close(resolve));
  return port;
}
async function get(url) {
  const response = await fetch(url, {signal: AbortSignal.timeout(1400)});
  if (!response.ok) throw new Error("HTTP " + response.status);
  return response.json();
}
async function send(url, method, params = {}) {
  const socket = new WebSocket(url);
  try {
    return await Promise.race([
      new Promise((resolve, reject) => {
        socket.addEventListener("open", () => socket.send(JSON.stringify({id: 1, method, params})), {once: true});
        socket.addEventListener("error", () => reject(new Error("CDP connection failed")), {once: true});
        socket.addEventListener("message", ({data}) => {
          const frame = JSON.parse(data);
          if (frame.id !== 1) return;
          if (frame.error) reject(new Error(frame.error.message));
          else resolve(frame.result);
        });
      }),
      pause(1800).then(() => {throw new Error("CDP timeout");}),
    ]);
  } finally { socket.close(); }
}
const launches = [];
async function launch(name, args = []) {
  const backendPort = await freePort();
  const debuggerPort = await freePort();
  const logFile = path.join(evidence, name + ".log");
  const env = {
    ...process.env,
    HOME: evidence,
    CANDLESCOPE_DESKTOP_USER_DATA: profile,
    CANDLESCOPE_PLUGIN_PLATFORM_V2_ROOT: path.dirname(store),
    CANDLESCOPE_PLUGIN_PLATFORM_V2_ENABLED: "1",
    CANDLESCOPE_RUNTIME_MODE: "LOCAL_OFFLINE",
    CANDLESCOPE_DESKTOP_UI_PORT: "0",
    CANDLESCOPE_DESKTOP_BACKEND_PORT: String(backendPort),
    CANDLESCOPE_DESKTOP_SIDECAR_TIMEOUT_MS: "90000",
    CANDLESCOPE_LOCAL_DATA_DIR: path.join(evidence, "local-data"),
    CANDLE_DATA_DIR: path.join(evidence, "data"),
    CANDLESCOPE_EXTENSIONS_SAFE_MODE: "0",
    BACKTEST_ENABLED: "0",
    REPLAY_ENABLED: "1",
  };
  for (const key of [
    "ELECTRON_RUN_AS_NODE", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV",
    "CANDLESCOPE_DESKTOP_URL", "CANDLESCOPE_DESKTOP_SKIP_SIDECAR",
    "CANDLESCOPE_DESKTOP_SIDECAR_COMMAND_JSON", "CANDLESCOPE_PYTHON",
  ]) delete env[key];
  const log = openSync(logFile, "w");
  const children = spawn(executable, ["--remote-debugging-port=" + debuggerPort, ...args], {
    stdio: ["ignore", log, log],
    env,
  });
  closeSync(log);
  const phase = {name, children, backend: "http://127.0.0.1:" + backendPort, debug: "http://127.0.0.1:" + debuggerPort, logFile};
  children.once("error", (error) => { phase.launchError = String(error); });
  launches.push(phase);
  return phase;
}
async function windowState(phase, expectedShell) {
  if (phase.children.exitCode !== null) throw new Error("candidate exited during startup");
  const pages = await get(phase.debug + "/json/list");
  const page = pages.find((page) => page.type === "page" && page.url.startsWith("http://127.0.0.1:"));
  if (!page) return null;
  const evaluate = await send(page.webSocketDebuggerUrl, "Runtime.evaluate", {
    expression: "({mounted: !!document.querySelector('.app-layout'), shell: document.querySelector('[data-startup-shell]')?.dataset.startupShell ?? null, href:location.pathname})",
    returnByValue: true,
  });
  const value = evaluate.result.value;
  return value?.mounted && value.shell === expectedShell ? {page, value} : null;
}
async function close(phase, page) {
  const browser = await get(phase.debug + "/json/version");
  await send(browser.webSocketDebuggerUrl, "Target.closeTarget", {targetId: page.id});
  await wait("full app exit", () => phase.children.exitCode !== null);
  assert.equal(phase.children.exitCode, 0);
  await wait("sidecar stopped", async () => {
    try { await get(phase.backend + "/health"); return false; }
    catch { return true; }
  });
}
async function prove(name, expectedShell, args) {
  const phase = await launch(name, args);
  let capabilities;
  await wait("backend healthy " + name, async () => { capabilities = await get(phase.backend + "/api/v1/replay/capabilities"); return capabilities; });
  assert.equal(capabilities.startupTakeover ?? null, expectedShell);
  const {page, value} = await wait("renderer " + name, () => windowState(phase, expectedShell));
  await close(phase, page);
  receipt.phases.push({name, shell: value.shell, page: value.href, runtime: capabilities.startupTakeover ?? null, exited: true});
  console.log("Passed", name, value);
}
try {
  await prove("01-normal-takeover", plugin);
  const badSource = path.join(evidence, "bad-source");
  cpSync(source, badSource, {recursive: true});
  const manifestPath = path.join(badSource, "manifest.json");
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  manifest.version = "2.0.0";
  writeFileSync(manifestPath, JSON.stringify(manifest));
  writeFileSync(path.join(badSource, "replay.py"),
    "def prepare(ctx):\n    async def wrap(default, *args, **kwargs):\n        raise RuntimeError('QA intentional takeover failure')\n    ctx.wrap_factory('replay', wrap)\n\ndef activate(ctx):\n    pass\n");
  const bad = stage(badSource, "bad");
  approve(bad);
  receipt.bad = bad.packageSha256;
  const failed = await launch("02-fault");
  const failureLog = path.join(profile, "logs", "desktop-startup-error.log");
  const backendLog = path.join(profile, "logs", "backend-sidecar.log");
  await wait("fault confirmed", () => existsSync(failureLog)
    && readFileSync(backendLog, "utf8").includes("QA intentional takeover failure"));
  await assert.rejects(() => get(failed.backend + "/health"));
  assert.match(readFileSync(failureLog, "utf8"), /Sidecar exited before it became healthy [(]3[)]/);
  assert.doesNotMatch(readFileSync(backendLog, "utf8"), /Fatal Python error/);
  // The startup-error dialog is modal. End only this failed QA process.
  failed.children.kill("SIGKILL");
  await wait("failed app closed", () => failed.children.exitCode !== null || failed.children.signalCode !== null);
  receipt.phases.push({name: "02-fault", startupError: true, backendHealthy: false, sidecarExitCode: 3, exited: true});
  console.log("Passed 02-fault");
  await prove("03-native-disable", null, ["--disable-unified-plugin=" + plugin]);
  const record = cli("list", "--root", store).plugins[plugin];
  assert.equal(record.enabled, false);
  assert.equal(record.packageSha256, bad.packageSha256);
  await prove("04-normal-restart", null);
  receipt.after = fingerprint(fixtureFile);
  assert.equal(receipt.after, before);
  assert.equal(cli("list", "--root", store).plugins[plugin].enabled, false);
  for (const digest of [good.packageSha256, bad.packageSha256]) {
    assert.equal(cli("review", "--root", store, digest).packageSha256, digest);
  }
  receipt.ok = true;
} catch (error) {
  receipt.failure = {
    message: String(error), cause: error.cause ? String(error.cause) : null,
    launches: launches.map(({name, launchError}) => ({name, launchError})),
  };
  throw error;
} finally {
  for (const phase of launches) {
    if (phase.children.exitCode === null && phase.children.signalCode === null) phase.children.kill("SIGTERM");
  }
  writeFileSync(receiptPath || path.join(evidence, "receipt.json"), JSON.stringify(receipt, null, 2) + "\n");
}
