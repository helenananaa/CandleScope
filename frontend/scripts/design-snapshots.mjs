#!/usr/bin/env node
// Design snapshots: captures named UI states in each theme and viewport so design
// changes can be reviewed before and after. Steps name i18n message keys and are
// resolved through the app's own `t()`, so captures work in any interface language.
//
// Requires the Vite dev server (the page imports /src modules) and the backend.
//
//   node scripts/design-snapshots.mjs --label baseline
//   node scripts/design-snapshots.mjs --label after --states market,alerts --themes dark
//   node scripts/design-snapshots.mjs --compare ../output/design-snapshots/baseline ../output/design-snapshots/after
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

export const SETTINGS_KEY = "candlescope-settings";

/** Named states. A step clicks the first visible control matching a message key, a literal text or a selector. */
export const STATES = [
  { name: "market", page: "/" },
  { name: "settings-appearance", page: "/", steps: [{ key: "shell.settings" }] },
  { name: "settings-network", page: "/", steps: [{ key: "shell.settings" }, { selector: ".st-nav-item", index: 1 }] },
  { name: "settings-exchanges", page: "/", steps: [{ key: "shell.settings" }, { selector: ".st-nav-item", index: 2 }] },
  { name: "settings-data", page: "/", steps: [{ key: "shell.settings" }, { selector: ".st-nav-item", index: 3 }] },
  { name: "settings-plugins", page: "/", steps: [{ key: "shell.settings" }, { selector: ".st-nav-item", index: 4 }] },
  { name: "indicators", page: "/", steps: [{ key: "shell.indicators", prefix: true }] },
  { name: "alerts", page: "/", steps: [{ key: "shell.alerts" }] },
  { name: "symbol-search", page: "/", steps: [{ key: "search.title", params: { modifier: "" }, prefix: true }] },
  { name: "export", page: "/", steps: [{ key: "drawing.export" }] },
  { name: "interval-menu", page: "/", steps: [{ key: "interval.openPicker" }] },
  { name: "layout-menu", page: "/", steps: [{ key: "workspace.currentLayout", prefix: true }] },
  { name: "history-study", page: "/", steps: [{ key: "study.title" }] },
  { name: "data-workbench", page: "/", steps: [
    { key: "shell.settings" }, { selector: ".st-nav-item", index: 3 }, { key: "settings.workbench.open" }] },
  { name: "rail-tape", page: "/", steps: [{ key: "rail.expandView", params: { title: { key: "rail.tape" } } }] },
  { name: "rail-accounts", page: "/", steps: [{ key: "rail.expandView", params: { title: { key: "rail.accounts" } } }] },
  { name: "chart-tester", page: "/", steps: [{ key: "chartTester.entryHint" }] },
  { name: "extension-recovery", page: "/", steps: [{ selector: ".extension-recovery > button" }] },
  { name: "replay-hub", page: "/replay.html" },
  { name: "strategy", page: "/strategy.html" },
  { name: "strategy-local-source", page: "/strategy.html?source=imported" },
  { name: "backtest", page: "/backtest.html" },
];

export function parseArgs(argv) {
  const args = {
    url: "http://127.0.0.1:15173",
    label: new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-"),
    out: "",
    themes: ["dark", "light"],
    viewports: [{ width: 1440, height: 900 }],
    locale: "zh-CN",
    states: [],
    chromePath: process.env.CHROME_PATH || "",
    loadWaitMs: 8000,
    settleMs: 1500,
    compare: null,
  };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    const next = () => {
      const value = argv[++i];
      if (value === undefined) throw new Error(`${arg} needs a value`);
      return value;
    };
    if (arg === "--url") args.url = next().replace(/\/$/, "");
    else if (arg === "--label") args.label = next();
    else if (arg === "--out") args.out = next();
    else if (arg === "--themes") args.themes = next().split(",").map((v) => v.trim()).filter(Boolean);
    else if (arg === "--viewports") args.viewports = next().split(",").map(parseViewport);
    else if (arg === "--locale") args.locale = next();
    else if (arg === "--states") args.states = next().split(",").map((v) => v.trim()).filter(Boolean);
    else if (arg === "--chrome") args.chromePath = next();
    else if (arg === "--load-wait") args.loadWaitMs = Number(next());
    else if (arg === "--settle") args.settleMs = Number(next());
    else if (arg === "--compare") args.compare = [next(), next()];
    else throw new Error(`Unknown option: ${arg}`);
  }
  for (const theme of args.themes) {
    if (!["dark", "light"].includes(theme)) throw new Error(`Unknown theme: ${theme}`);
  }
  const unknown = args.states.filter((name) => !STATES.some((state) => state.name === name));
  if (unknown.length) throw new Error(`Unknown state(s): ${unknown.join(", ")}`);
  if (!args.out) args.out = path.resolve(import.meta.dirname, "../../output/design-snapshots", args.label);
  return args;
}

function parseViewport(value) {
  const match = /^(\d{3,4})x(\d{3,4})$/.exec(value.trim());
  if (!match) throw new Error(`Viewport must look like 1440x900: ${value}`);
  return { width: Number(match[1]), height: Number(match[2]) };
}

export function snapshotFileName(state, theme, viewport) {
  return `${state}--${theme}--${viewport.width}x${viewport.height}.png`;
}

/** Text before the first "(" or "{" of a label, for keys whose labels carry counts or shortcuts. */
export function labelPrefix(label) {
  return label.split(/[({]/)[0].trim();
}

export function findChrome(explicitPath) {
  return [
    explicitPath,
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
  ].filter(Boolean).find((candidate) => fs.existsSync(candidate));
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export async function openBrowser(chromePath) {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "candlescope-design-snapshots-"));
  const port = 9400 + Math.floor(Math.random() * 400);
  const chrome = spawn(chromePath, [
    "--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
    "--no-first-run", "--no-default-browser-check", "--hide-scrollbars", "about:blank",
  ], { stdio: "ignore" });
  let targets = null;
  for (let attempt = 0; attempt < 75 && !targets; attempt++) {
    try {
      targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
    } catch {
      await wait(200);
    }
  }
  if (!targets) throw new Error("Chrome DevTools endpoint did not start");
  const page = targets.find((target) => target.type === "page");
  const socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  let nextId = 0;
  const pending = new Map();
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(String(event.data));
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    }
  });
  const send = (method, params = {}) => new Promise((resolve) => {
    const id = ++nextId;
    pending.set(id, resolve);
    socket.send(JSON.stringify({ id, method, params }));
  });
  const close = async () => {
    socket.close();
    const exited = new Promise((resolve) => chrome.once("exit", resolve));
    chrome.kill();
    // Chrome keeps writing its profile until it exits; removing it earlier fails with ENOTEMPTY.
    await Promise.race([exited, wait(5000)]);
    try {
      fs.rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    } catch {
      // A leftover temporary profile is harmless; the OS clears its temp directory.
    }
  };
  return { send, close };
}

// Runs in the page: resolves a step against the app's own i18n module and clicks the match.
export const CLICK_STEP = `async (step) => {
  const { t } = await import("/src/i18n/index.ts");
  const resolveParams = (params = {}) => Object.fromEntries(Object.entries(params)
    .map(([name, value]) => [name, value && typeof value === "object" ? t(value.key) : value]));
  const norm = (text) => (text || "").replace(/\\s+/g, " ").trim();
  const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  if (step.selector) {
    const matches = [...document.querySelectorAll(step.selector)].filter(visible);
    const el = matches[step.index ?? 0];
    if (!el) return "not found: " + step.selector;
    el.click();
    return "ok";
  }
  let label = norm(t(step.key, resolveParams(step.params)));
  if (step.prefix) label = label.split(/[({]/)[0].trim();
  const controls = [...document.querySelectorAll("button, a, [role=tab], [role=button], summary")].filter(visible);
  const names = (el) => [el.getAttribute("aria-label"), el.getAttribute("title"), el.textContent].map(norm);
  const el = controls.find((c) => names(c).some((name) => step.prefix ? name.startsWith(label) : name === label));
  if (!el) return "not found: " + step.key + " (" + label + ")";
  el.click();
  return "ok";
}`;

/** Loads a state's page and runs its steps; returns the steps that did not succeed. */
export async function visitState(browser, args, state) {
  await browser.send("Page.navigate", { url: args.url + state.page });
  await wait(state.page === "/" ? args.loadWaitMs : Math.round(args.loadWaitMs * 0.75));
  const problems = [];
  for (const step of state.steps ?? []) {
    const result = await browser.send("Runtime.evaluate", {
      expression: `(${CLICK_STEP})(${JSON.stringify(step)})`, awaitPromise: true, returnByValue: true,
    });
    const outcome = result.result?.exceptionDetails ? `error: ${result.result.exceptionDetails.text}` : result.result?.result?.value;
    if (outcome !== "ok") problems.push(String(outcome));
    await wait(args.settleMs);
  }
  return problems;
}

async function capture(args) {
  const chromePath = findChrome(args.chromePath);
  if (!chromePath) throw new Error("Chrome or Edge was not found. Set CHROME_PATH or pass --chrome.");
  fs.mkdirSync(args.out, { recursive: true });
  const states = args.states.length ? STATES.filter((state) => args.states.includes(state.name)) : STATES;
  const manifest = { label: args.label, url: args.url, locale: args.locale, capturedAt: new Date().toISOString(), shots: [] };
  for (const theme of args.themes) {
    // A fresh profile per theme keeps captures independent of earlier runs and of each other.
    const browser = await openBrowser(chromePath);
    try {
      await browser.send("Page.enable");
      await browser.send("Page.addScriptToEvaluateOnNewDocument", {
        source: `try { const k = ${JSON.stringify(SETTINGS_KEY)}; const s = JSON.parse(localStorage.getItem(k) || "{}");
          s.theme = ${JSON.stringify(theme)}; s.locale = ${JSON.stringify(args.locale)}; localStorage.setItem(k, JSON.stringify(s)); } catch {}`,
      });
      for (const viewport of args.viewports) {
        await browser.send("Emulation.setDeviceMetricsOverride", { ...viewport, deviceScaleFactor: 1, mobile: false });
        for (const state of states) {
          const problems = await visitState(browser, args, state);
          const shot = await browser.send("Page.captureScreenshot", { format: "png" });
          const file = snapshotFileName(state.name, theme, viewport);
          fs.writeFileSync(path.join(args.out, file), Buffer.from(shot.result.data, "base64"));
          manifest.shots.push({ state: state.name, theme, viewport, file, problems });
          console.log(`${problems.length ? "!" : "✓"} ${file}${problems.length ? `  (${problems.join("; ")})` : ""}`);
        }
      }
    } finally {
      await browser.close();
    }
  }
  const merged = mergeManifest(readManifest(args.out), manifest);
  fs.writeFileSync(path.join(args.out, "manifest.json"), `${JSON.stringify(merged, null, 2)}\n`);
  console.log(`\n${manifest.shots.length} snapshots in ${args.out} (${merged.shots.length} in the manifest)`);
}

function readManifest(dir) {
  try {
    return JSON.parse(fs.readFileSync(path.join(dir, "manifest.json"), "utf8"));
  } catch {
    return null;
  }
}

/** Later runs into the same label add or replace shots instead of discarding earlier ones. */
export function mergeManifest(previous, next) {
  if (!previous?.shots) return next;
  const byFile = new Map(previous.shots.map((shot) => [shot.file, shot]));
  for (const shot of next.shots) byFile.set(shot.file, shot);
  return { ...next, shots: [...byFile.values()].sort((a, b) => a.file.localeCompare(b.file)) };
}

/** Writes compare.html pairing files that exist in both runs. */
export function compareHtml(before, after, files) {
  const rel = (dir, file) => path.relative(after, path.join(dir, file)).split(path.sep).join("/");
  const rows = files.map((file) => `<section><h2>${file}</h2><div class="pair">
<figure><img loading="lazy" src="${rel(before, file)}"><figcaption>${path.basename(before)}</figcaption></figure>
<figure><img loading="lazy" src="${rel(after, file)}"><figcaption>${path.basename(after)}</figcaption></figure></div></section>`).join("\n");
  return `<!doctype html><meta charset="utf-8"><title>Design snapshots: ${path.basename(before)} vs ${path.basename(after)}</title>
<style>body{margin:0;padding:24px;background:#141518;color:#e9eaec;font:14px system-ui,sans-serif}h2{font-size:14px;font-weight:600;margin:32px 0 8px}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px}figure{margin:0}img{width:100%;display:block;border-radius:6px}figcaption{color:#a6a9b0;margin-top:4px}</style>
<h1>${path.basename(before)} → ${path.basename(after)}</h1>
${rows}
`;
}

function compare([beforeDir, afterDir]) {
  const before = path.resolve(beforeDir);
  const after = path.resolve(afterDir);
  const files = fs.readdirSync(after).filter((file) => file.endsWith(".png") && fs.existsSync(path.join(before, file))).sort();
  const out = path.join(after, "compare.html");
  fs.writeFileSync(out, compareHtml(before, after, files));
  console.log(`${files.length} pairs: ${out}`);
}

export async function main(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);
  if (args.compare) compare(args.compare);
  else await capture(args);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  });
}
