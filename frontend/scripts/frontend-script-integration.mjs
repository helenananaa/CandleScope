/** Owns its production test build, loopback server, browser and private profile. */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { build, preview } from "vite";

const root = fileURLToPath(new URL("../", import.meta.url));
const annotationTools = process.argv.includes("--annotation-tools");
const backendSyntheticPinned = process.argv.includes("--backend-synthetic-pinned");
const backendSynthetic = backendSyntheticPinned || process.argv.includes("--backend-synthetic");
const rangeMeasure = process.argv.includes("--range-measure") || annotationTools;
const marketHealth = process.argv.includes("--market-health");
const chartMarketPrepend = process.argv.includes("--chart-market-prepend");
const chartMarketCalculation = chartMarketPrepend || process.argv.includes("--chart-market-calculation");
const chartCalculation = chartMarketCalculation || process.argv.includes("--chart-calculation");
const indicatorFlow = process.argv.includes("--indicator-flow");
const native = process.argv.includes("--native");
if (native && !marketHealth) throw new Error("The isolated native host currently supports only --market-health");
const intervalAdmission = process.argv.includes("--interval-admission");
const replayResize = process.argv.includes("--replay-resize");
const replay = process.argv.includes("--replay-visible") || replayResize;
const accountOverlays = process.argv.includes("--account-overlays");
const trainingInput = process.argv.includes("--replay-training-input");
const historyStages = process.argv.includes("--history-stages");
const quickReplayStep = process.argv.includes("--quick-replay-step");
const chartTimeNavigation = process.argv.includes("--chart-time-navigation");
const replayNotes = process.argv.includes("--replay-notes");
const fixture = backendSyntheticPinned ? "backend-synthetic-pinned-browser.html" : backendSynthetic ? "backend-synthetic-browser.html" : chartMarketPrepend ? "chart-market-prepend-browser.html" : chartMarketCalculation ? "chart-market-calculation-browser.html" : chartCalculation ? "chart-calculation-browser.html" : replayNotes ? "replay-notes-browser.html" : replayResize ? "replay-resize-browser.html" : annotationTools ? "annotation-tools-browser.html" : rangeMeasure ? "range-measure-browser.html" : accountOverlays ? "chart-account-overlays-browser.html" : quickReplayStep ? "quick-replay-step-browser.html" : chartTimeNavigation ? "chart-time-navigation-browser.html" : indicatorFlow ? "indicator-flow-browser.html" : marketHealth ? "market-health-browser.html" : historyStages ? "history-stages-browser.html" : intervalAdmission ? "interval-admission-browser.html" : trainingInput ? "replay-training-input-browser.html" : replay ? "replay-visible-indicators-browser.html" : "frontend-script-browser.html";
const requested = process.argv.indexOf("--out");
const output = requested === -1 ? fs.mkdtempSync(path.join(os.tmpdir(), "candlescope-frontend-js-")) : path.resolve(process.argv[requested + 1]);
fs.mkdirSync(output, { recursive: true });
const profile = fs.mkdtempSync(path.join(output, "browser-profile-"));
const candidates = [process.env.CHROME_PATH,
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
  process.env.PROGRAMFILES && path.join(process.env.PROGRAMFILES, "Google/Chrome/Application/chrome.exe"),
  process.env.PROGRAMFILES && path.join(process.env.PROGRAMFILES, "Microsoft/Edge/Application/msedge.exe"),
];
const electron = process.env.ELECTRON_PATH || path.join(root, "node_modules/electron/dist", process.platform === "darwin"
  ? "Electron.app/Contents/MacOS/Electron" : process.platform === "win32" ? "electron.exe" : "electron");
const chrome = native ? electron : candidates.find(value => value && fs.existsSync(value));
if (!chrome || !fs.existsSync(chrome)) throw new Error(native ? "Set ELECTRON_PATH to an installed Electron executable" : "Set CHROME_PATH to an installed Chrome or Edge executable");
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

class CDP {
  static async open(url) {
    const client = new CDP();
    client.socket = new WebSocket(url);
    client.id = 0; client.pending = new Map(); client.events = [];
    client.socket.onmessage = event => {
      const item = JSON.parse(event.data);
      if (!item.id) { client.events.push(item); return; }
      const pending = client.pending.get(item.id);
      if (!pending) return;
      client.pending.delete(item.id); clearTimeout(pending.timer);
      if (item.error) pending.reject(new Error(JSON.stringify(item.error)));
      else pending.resolve(item.result);
    };
    await new Promise((resolve, reject) => {
      client.socket.onopen = resolve;
      client.socket.onerror = () => reject(new Error("Test browser connection failed"));
    });
    return client;
  }
  send(method, params = {}, timeoutMs = 30_000) {
    return new Promise((resolve, reject) => {
      const id = ++this.id;
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }
}

let server, child, browser, page;
const receipt = { scope: native ? "Isolated Electron host, production-minified renderer and controlled market transport; not installed-release qualification" : (replay || accountOverlays || rangeMeasure) ? "Real Chromium, minified application fixture with development React act lifecycle; not native application qualification" : "Real Chromium, production-minified browser fixture and real React lifecycle; not native application qualification", output };
try {
  const destination = path.join(output, "dist");
  await build({ root, ...((replay || accountOverlays || rangeMeasure) ? { define: { "process.env.NODE_ENV": JSON.stringify("development") } } : {}), build: { outDir: destination, rollupOptions: { input: path.join(root, "scripts", fixture) } } });
  server = await preview({ root, build: { outDir: destination }, preview: { host: "127.0.0.1", port: 0, strictPort: false } });
  const url = server.resolvedUrls.local[0] + "scripts/" + fixture
    + (replayNotes ? "?backend=" + encodeURIComponent(process.env.CANDLESCOPE_QA_BACKEND_URL ?? "") : "");
  const log = fs.openSync(path.join(output, "chrome.log"), "a");
  let args = ["--headless=new", "--remote-debugging-port=0", "--no-first-run", "--no-default-browser-check", `--user-data-dir=${profile}`, url];
  if (native) {
    const host = path.join(output, "electron-host.cjs");
    fs.writeFileSync(host, `const {app,BrowserWindow}=require("electron");
app.setPath("userData",${JSON.stringify(profile)});
app.whenReady().then(()=>{const window=new BrowserWindow({width:1280,height:900,webPreferences:{contextIsolation:true,sandbox:true}});window.loadURL(${JSON.stringify(url)});});
app.on("window-all-closed",()=>app.quit());
`);
    args = ["--remote-debugging-port=0", `--user-data-dir=${profile}`, host];
  }
  child = spawn(chrome, args, { stdio: ["ignore", log, log] });
  fs.closeSync(log);
  let lines;
  const browserStartDeadline = Date.now() + Math.min(120_000,
    Math.max(10_000, Number(process.env.CANDLESCOPE_TEST_BROWSER_START_TIMEOUT_MS) || 10_000));
  while (Date.now() < browserStartDeadline) {
    try { lines = fs.readFileSync(path.join(profile, "DevToolsActivePort"), "utf8").trim().split("\n"); break; } catch { /* browser not ready */ }
    if (native) {
      const match = fs.readFileSync(path.join(output, "chrome.log"), "utf8").match(/DevTools listening on ws:\/\/127\.0\.0\.1:(\d+)(\/devtools\/browser\/[^\s]+)/);
      if (match) { lines = [match[1], match[2]]; break; }
    }
    await sleep(100);
  }
  if (!lines) throw new Error("Owned test browser did not start");
  const base = `http://127.0.0.1:${lines[0]}`;
  let version, tab, lastProbeError;
  while (Date.now() < browserStartDeadline) {
    if (child.exitCode !== null || child.signalCode !== null) throw new Error("Owned test browser exited during readiness");
    try {
      version = await (await fetch(base + "/json/version", { signal: AbortSignal.timeout(1000) })).json();
      const tabs = await (await fetch(base + "/json/list", { signal: AbortSignal.timeout(1000) })).json();
      tab = tabs.find(item => item.type === "page" && item.url === url);
      if (version.webSocketDebuggerUrl && tab?.webSocketDebuggerUrl) break;
    } catch (error) { lastProbeError = String(error); }
    await sleep(100);
  }
  if (!version?.webSocketDebuggerUrl || !tab?.webSocketDebuggerUrl) {
    throw new Error("Owned test browser debugger/page did not become ready: " + (lastProbeError || "page missing"));
  }
  receipt.browser = version.Browser;
  browser = await CDP.open(version.webSocketDebuggerUrl);
  await browser.send("Target.setDiscoverTargets", { discover: true });
  page = await CDP.open(tab.webSocketDebuggerUrl);
  await page.send("Runtime.enable");
  // The tab can be discoverable while its initial document is still being
  // replaced. Probe readiness without starting the fixture, then invoke it
  // exactly once in the committed document.
  const checkName = chartCalculation ? "__chartCalculationCheck" : indicatorFlow ? "__indicatorFlowCheck" : marketHealth ? "__marketHealthCheck" : intervalAdmission ? "__intervalAdmissionCheck" : "__frontendScriptCheck";
  let fixtureReady = false;
  for (let attempt = 0; attempt < 100; attempt++) {
    try {
      const ready = await page.send("Runtime.evaluate", {
        expression: `document.readyState === 'complete' && typeof window.${checkName} === 'function'`,
        returnByValue: true,
      });
      if (ready.result?.value === true) { fixtureReady = true; break; }
    } catch (error) {
      if (!String(error).includes("Execution context was destroyed")) throw error;
    }
    await sleep(100);
  }
  if (!fixtureReady) throw new Error("Fixture did not load");
  const pendingResult = page.send("Runtime.evaluate", {
    expression: `window.${checkName}()`,

    awaitPromise: true, returnByValue: true,
  }, backendSynthetic ? 90_000 : 30_000);
  if (replayNotes) {
    let completed = false;
    void pendingResult.then(() => { completed = true; }, () => { completed = true; });
    receipt.screenshots = [];
    while (!completed) {
      const requestedCapture = await page.send("Runtime.evaluate", { expression: "window.__replayNoteCapture ?? null", returnByValue: true });
      const name = requestedCapture.result?.value;
      if (typeof name === "string") {
        if (!/^[a-z-]{1,80}$/.test(name)) throw new Error("Invalid note capture name");
        const capture = await page.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
        const filename = name + ".png";
        fs.writeFileSync(path.join(output, filename), Buffer.from(capture.data, "base64"));
        receipt.screenshots.push(filename);
        await page.send("Runtime.evaluate", { expression: "window.__replayNoteCapture = null" });
      }
      await sleep(50);
    }
  }
  const result = await pendingResult;
  receipt.result = result;
  let targets = await browser.send("Target.getTargets");
  receipt.immediateWorkerCount = targets.targetInfos.filter(item => item.type === "worker").length;
  for (let i = 0; i < 40 && targets.targetInfos.some(item => ["worker", "shared_worker"].includes(item.type)); i++) {
    await sleep(50); targets = await browser.send("Target.getTargets");
  }
  receipt.remainingWorkers = targets.targetInfos.filter(item => ["worker", "shared_worker"].includes(item.type));
  receipt.exceptions = page.events.filter(item => item.method === "Runtime.exceptionThrown");
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
  if (receipt.exceptions.length) throw new Error("Renderer exceptions occurred during the browser fixture");
  if (receipt.remainingWorkers.length) throw new Error("Browser workers remained after the cleanup deadline");
  if (!backendSynthetic && !chartCalculation && !chartTimeNavigation && !historyStages && !intervalAdmission && !marketHealth && !indicatorFlow && !quickReplayStep) {
    const editor = await page.send("Runtime.evaluate", { expression: "window.__frontendScriptEditorCheck()", awaitPromise: true, returnByValue: true });
    receipt.editor = editor;
    if (editor.exceptionDetails) throw new Error(JSON.stringify(editor.exceptionDetails));
  }
  receipt.passed = true;
} catch (error) {
  receipt.passed = false; receipt.error = String(error); process.exitCode = 1;
} finally {
  page?.socket.close();
  try { await browser?.send("Browser.close"); } catch { /* browser may close without replying */ }
  browser?.socket.close();
  if (child) {
    for (let i = 0; i < 50 && child.exitCode === null; i++) await sleep(100);
    if (child.exitCode === null) child.kill("SIGTERM");
    receipt.browserExitCode = child.exitCode;
  }
  await new Promise(resolve => server ? server.httpServer.close(resolve) : resolve());
  fs.writeFileSync(path.join(output, "result.json"), JSON.stringify(receipt, null, 2));
  console.log(JSON.stringify(receipt));
}
