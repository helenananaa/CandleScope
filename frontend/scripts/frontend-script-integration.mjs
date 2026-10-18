/** Owns its production test build, loopback server, browser and private profile. */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { build, preview } from "vite";

const root = fileURLToPath(new URL("../", import.meta.url));
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
const chrome = candidates.find(value => value && fs.existsSync(value));
if (!chrome) throw new Error("Set CHROME_PATH to an installed Chrome or Edge executable");
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
  send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++this.id;
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 30_000);
      this.pending.set(id, { resolve, reject, timer });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }
}

let server, child, browser, page;
const receipt = { scope: "Real Chromium, production-minified browser fixture and real React lifecycle; not native application qualification", output };
try {
  const destination = path.join(output, "dist");
  await build({ root, build: { outDir: destination, rollupOptions: { input: path.join(root, "scripts/frontend-script-browser.html") } } });
  server = await preview({ root, build: { outDir: destination }, preview: { host: "127.0.0.1", port: 0, strictPort: false } });
  const url = server.resolvedUrls.local[0] + "scripts/frontend-script-browser.html";
  const log = fs.openSync(path.join(output, "chrome.log"), "a");
  child = spawn(chrome, ["--headless=new", "--remote-debugging-port=0", "--no-first-run", "--no-default-browser-check", `--user-data-dir=${profile}`, url], { stdio: ["ignore", log, log] });
  fs.closeSync(log);
  let lines;
  for (let i = 0; i < 100; i++) {
    try { lines = fs.readFileSync(path.join(profile, "DevToolsActivePort"), "utf8").trim().split("\n"); break; } catch { /* browser not ready */ }
    await sleep(100);
  }
  if (!lines) throw new Error("Owned test browser did not start");
  const base = `http://127.0.0.1:${lines[0]}`;
  const version = await (await fetch(base + "/json/version")).json();
  receipt.browser = version.Browser;
  browser = await CDP.open(version.webSocketDebuggerUrl);
  await browser.send("Target.setDiscoverTargets", { discover: true });
  const tabs = await (await fetch(base + "/json/list")).json();
  const tab = tabs.find(item => item.type === "page" && item.url === url);
  if (!tab) throw new Error("Owned integration page is missing");
  page = await CDP.open(tab.webSocketDebuggerUrl);
  await page.send("Runtime.enable");
  const result = await page.send("Runtime.evaluate", {
    expression: "new Promise((resolve,reject)=>{const until=Date.now()+10000;const ready=()=>{if(window.__frontendScriptCheck)Promise.resolve(window.__frontendScriptCheck()).then(resolve,reject);else if(Date.now()>until)reject(new Error('Fixture did not load'));else setTimeout(ready,20);};ready();})",
    awaitPromise: true, returnByValue: true,
  });
  receipt.result = result;
  let targets = await browser.send("Target.getTargets");
  receipt.immediateWorkerCount = targets.targetInfos.filter(item => item.type === "worker").length;
  for (let i = 0; i < 40 && targets.targetInfos.some(item => ["worker", "shared_worker"].includes(item.type)); i++) {
    await sleep(50); targets = await browser.send("Target.getTargets");
  }
  receipt.remainingWorkers = targets.targetInfos.filter(item => ["worker", "shared_worker"].includes(item.type));
  receipt.exceptions = page.events.filter(item => item.method === "Runtime.exceptionThrown");
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
  if (receipt.remainingWorkers.length) throw new Error("Browser workers remained after the cleanup deadline");
  const editor = await page.send("Runtime.evaluate", { expression: "window.__frontendScriptEditorCheck()", awaitPromise: true, returnByValue: true });
  receipt.editor = editor;
  if (editor.exceptionDetails) throw new Error(JSON.stringify(editor.exceptionDetails));
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
