/** Real packaged Electron acceptance. Isolated profile; no exchange or account activity. */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { createHash } from "node:crypto";
import { existsSync, readFileSync, writeFileSync, mkdirSync, mkdtempSync, appendFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const argument = (name, fallback) => { const index = process.argv.indexOf(name); return index < 0 ? fallback : process.argv[index + 1]; };
const executableArgument = argument("--executable");
assert.ok(executableArgument, "Pass --executable pointing to a completed packaged build");
const executable = path.resolve(executableArgument);
const parent = path.resolve(argument("--out", "output/playwright/trusted-extensions-desktop"));
mkdirSync(parent, { recursive: true });
const root = mkdtempSync(path.join(parent, "run-"));
const receipts = path.join(root, "receipts");
mkdirSync(receipts);
const python = argument("--python", path.join(repo, ".venv", "Scripts", "python.exe"));
const require = createRequire(import.meta.url);
const { _electron: electron } = require(argument("--playwright-module", "playwright-core"));
const built = spawnSync(python, [path.join(repo, "backend/tests/build_trusted_extension_probes.py"), "--out", path.join(root, "packages")], { stdio: "inherit", windowsHide: true });
assert.equal(built.status, 0, "probe package build");
const environment = { ...process.env, CANDLESCOPE_DESKTOP_USER_DATA: path.join(root, "profile"),
  CANDLE_DATA_DIR: path.join(root, "data"), CANDLESCOPE_LOCAL_DATA_DIR: path.join(root, "local-data"),
  CANDLESCOPE_PLUGIN_PLATFORM_V2_ROOT: path.join(root, "plugins"), CANDLESCOPE_PLUGIN_PLATFORM_V2_ENABLED: "1",
  CANDLESCOPE_RUNTIME_MODE: "LOCAL_OFFLINE", BACKTEST_ENABLED: "0", CANDLESCOPE_EXTENSIONS_SAFE_MODE: "0",
  CANDLESCOPE_DESKTOP_UI_PORT: "0", CANDLESCOPE_DESKTOP_BACKEND_PORT: "18088",
  CANDLESCOPE_EXTENSION_PROBE_OUT: receipts,
};
for (const key of ["ELECTRON_RUN_AS_NODE", "CANDLESCOPE_PYTHON", "CANDLESCOPE_DESKTOP_URL", "CANDLESCOPE_DESKTOP_SKIP_SIDECAR", "CANDLESCOPE_DESKTOP_SIDECAR_COMMAND_JSON", "PYTHONPATH",
  "CANDLESCOPE_DESKTOP_SPIKE_OUT", "CANDLESCOPE_DESKTOP_RESTORE_PROBE_OUT", "CANDLESCOPE_DESKTOP_PHASE7_OUT", "CANDLESCOPE_DESKTOP_PHASE8_OUT"]) delete environment[key];
const report = { schema: "candlescope.extension-desktop-qualification/1", startedAt: new Date().toISOString(), executable,
  root, runtimeMode: "LOCAL_OFFLINE", result: "running", phases: [], failures: [], artifacts: {} };
for (const relative of ["CandleScope.exe", "resources/app.asar", "resources/backend/app/trusted_extensions/api.py",
  "resources/backend/app/trusted_extensions/runtime.py", "resources/backend/app/trusted_extensions/store.py",
  "resources/backend/app/desktop_sidecar.py", "resources/python-runtime/manifest.json"]) {
  report.artifacts[relative] = createHash("sha256").update(readFileSync(path.join(path.dirname(executable), relative))).digest("hex");
}
const save = () => writeFileSync(path.join(root, "report.json"), JSON.stringify(report, null, 2));
const record = (name, evidence) => { report.phases.push({ name, evidence }); save(); console.log(`PASS ${name}`); };
const events = (realm) => {
  const file = path.join(receipts, `${realm}.jsonl`);
  return existsSync(file) ? readFileSync(file, "utf8").trim().split("\n").filter(Boolean).map((line) => JSON.parse(line)) : [];
};
const interruptedBackendPids = new Set();
function verifyRealmCleanup(realm) {
  const receipt = events(realm);
  for (const activation of receipt.filter((item) => item.event === "activate")) {
    if (realm === "backend" && interruptedBackendPids.has(activation.pid)) continue;
    const disposal = receipt.filter((item) => item.pid === activation.pid && ["deactivate", "cleanup"].includes(item.event));
    assert.deepEqual(disposal.map((item) => item.event).sort(), ["cleanup", "deactivate"], `${realm} cleanup for PID ${activation.pid}`);
  }
}
function processAlive(pid) {
  try { process.kill(pid, 0); return true; }
  catch (error) { if (error.code === "ESRCH") return false; throw error; }
}
let app;
let page;
let run = 0;
const zhEn = (zh, en) => new RegExp(`^(?:${zh}|${en})$`);
async function launch(safe = false) {
  run++;
  report.bootAttempts = run;
  save();
  app = await electron.launch({ executablePath: executable, args: safe ? ["--extensions-safe-mode"] : [], env: environment, timeout: 60_000 });
  app.process().stderr.on("data", (chunk) => appendFileSync(path.join(root, `process-${run}.log`), chunk));
  page = await app.firstWindow({ timeout: 60_000 });
  page.setDefaultTimeout(20_000);
  await page.getByRole("button", { name: /^(扩展恢复|Extension recovery)/ }).waitFor();
  const identity = await app.evaluate(({ app }) => ({ packaged: app.isPackaged, resources: process.resourcesPath, userData: app.getPath("userData"), pid: process.pid }));
  assert.equal(identity.packaged, true);
  assert.equal(path.resolve(identity.userData), path.join(root, "profile"));
  writeFileSync(path.join(root, `page-${run}.txt`), await page.locator("body").ariaSnapshot());
  return identity;
}
async function close(verifyCleanup = true) {
  const previous = app; app = null;
  if (!previous) return;
  await previous.close();
  if (verifyCleanup) for (const realm of ["backend", "desktop"]) verifyRealmCleanup(realm);
}
async function manager() {
  if (!await page.getByRole("heading", { name: zhEn("可信扩展", "Trusted extensions") }).isVisible())
    await page.getByRole("button", { name: /^(扩展恢复|Extension recovery)/ }).click();
}
async function confirm() {
  await page.getByRole("checkbox", { name: zhEn("我信任并启用这个版本", "I trust and enable this version") }).check();
  await page.getByRole("button", { name: zhEn("确认启用", "Enable this version") }).click();
  await page.getByRole("region", { name: zhEn("扩展授权", "Extension approval") }).waitFor({ state: "hidden" });
  await page.getByRole("button", { name: zhEn("刷新", "Refresh") }).waitFor();
}
async function install(file) {
  await manager();
  await page.getByLabel(zhEn("导入扩展包", "Import extension package")).setInputFiles(file);
  await confirm();
}
async function action(name, actionZh, actionEn) {
  await manager();
  await page.locator(".extension-item").filter({ hasText: name }).getByRole("button", { name: zhEn(actionZh, actionEn) }).click();
}
async function version(value, target = page) {
  await target.waitForFunction((expected) => window.__extensionQualification?.version === expected && window.__extensionQualification.count === 1, value);
}
async function runtimeStatus(realm, status) {
  await manager();
  await page.locator(".extension-item").filter({ hasText: "Lifecycle qualification" })
    .locator(`[data-extension-runtime=${realm}][data-runtime-status=${status}]`).waitFor();
}
function activated(realm, versions) {
  const actual = events(realm).filter((item) => item.event === "activate").map((item) => item.version);
  assert.deepEqual(actual, versions, `${realm} process activations`);
}
save();
try {
  const identity = await launch();
  await install(path.join(repo, "output/trusted-extensions/paper.csext"));
  await install(path.join(repo, "output/trusted-extensions/terminal.csext"));
  await install(path.join(root, "packages/probe-1.0.0.csext"));
  await version("1.0.0");
  await runtimeStatus("backend", "pending-start"); await runtimeStatus("desktop", "pending-start");
  activated("backend", []); activated("desktop", []);
  record("install-is-restart-bound", identity);
  await close();

  await launch();
  await version("1.0.0");
  await runtimeStatus("backend", "running"); await runtimeStatus("desktop", "running");
  activated("backend", ["1.0.0"]); activated("desktop", ["1.0.0"]);
  const [second] = await Promise.all([app.waitForEvent("window"), page.evaluate(() => window.candlescopeDesktop.openAppPage(new URL("local.html", location.href).href))]);
  await version("1.0.0", second);
  activated("backend", ["1.0.0"]); activated("desktop", ["1.0.0"]);
  assert.equal(await page.locator(".terminal-extension-label").count(), 1);
  record("three-realms-and-second-window", { frontendWindows: 2, backendActivations: 1, desktopActivations: 1 });
  await second.close();
  await install(path.join(root, "packages/probe-1.1.0.csext"));
  await version("1.1.0");
  await runtimeStatus("backend", "pending-restart"); await runtimeStatus("desktop", "pending-restart");
  await page.locator(".extension-item").filter({ hasText: "Lifecycle qualification" }).screenshot({ path: path.join(root, "pending-restart.png") });
  activated("backend", ["1.0.0"]); activated("desktop", ["1.0.0"]);
  await close();
  for (const realm of ["backend", "desktop"]) assert.deepEqual(events(realm).slice(-2).map((item) => item.event).sort(), ["cleanup", "deactivate"]);
  record("upgrade-and-graceful-disposal", { previousVersion: "1.0.0", desiredVersion: "1.1.0" });

  await launch();
  await version("1.1.0");
  activated("backend", ["1.0.0", "1.1.0"]); activated("desktop", ["1.0.0", "1.1.0"]);
  await manager();
  await page.locator(".extension-item").filter({ hasText: "Lifecycle qualification" }).getByRole("button", { name: /查看旧版本|Review previous version/ }).click();
  await confirm();
  await version("1.0.0");
  await close();
  await launch();
  await version("1.0.0");
  activated("backend", ["1.0.0", "1.1.0", "1.0.0"]); activated("desktop", ["1.0.0", "1.1.0", "1.0.0"]);
  record("rollback-applies-after-restart", { versions: ["1.0.0", "1.1.0", "1.0.0"] });
  await action("Lifecycle qualification", "停用", "Disable");
  await page.waitForFunction(() => !window.__extensionQualification);
  await runtimeStatus("backend", "pending-stop"); await runtimeStatus("desktop", "pending-stop");
  await close();
  await launch();
  activated("backend", ["1.0.0", "1.1.0", "1.0.0"]); activated("desktop", ["1.0.0", "1.1.0", "1.0.0"]);
  assert.equal(await page.evaluate(() => window.__extensionQualification), undefined);
  await action("Lifecycle qualification", "启用", "Enable"); await confirm(); await version("1.0.0");
  await close();
  await launch(true);
  await manager();
  await page.getByText(/恢复模式：|Recovery mode:/).waitFor();
  assert.equal(await page.locator(".terminal-extension-label").count(), 0);
  assert.equal(await page.evaluate(() => window.__extensionQualification), undefined);
  activated("backend", ["1.0.0", "1.1.0", "1.0.0"]); activated("desktop", ["1.0.0", "1.1.0", "1.0.0"]);
  await page.screenshot({ path: path.join(root, "safe-mode.png") });
  record("disable-and-global-safe-mode", { managerAvailable: true, executedRealms: 0 });
  await close();

  await launch();
  await install(path.join(root, "packages/broken.csext"));
  await page.getByText(/Qualification frontend failure/).waitFor();
  assert.equal(await page.locator('style[data-extension-owner="qualification.broken"]').count(), 0);
  await close();
  await launch();
  await manager();
  await page.getByText(/Qualification frontend failure/).waitFor();
  await page.getByText(/Qualification backend failure/).waitFor();
  await page.getByText(/Qualification desktop failure/).waitFor();
  await page.locator(".extension-item").filter({ hasText: "Failure qualification" }).screenshot({ path: path.join(root, "failure-recovery.png") });
  record("activation-failure-keeps-manager-available", { running: true });
  await action("Failure qualification", "停用", "Disable");
  await install(path.join(root, "packages/crash.csext"));
  await close();
  const beforeCrash = new Set(events("backend").map((item) => item.pid));
  let interrupted = false;
  let interruption;
  try { await launch(); } catch (error) { interrupted = true; interruption = String(error); }
  assert.equal(interrupted, true, "native probe must interrupt its first boot");
  await close(false).catch(() => {});
  // Playwright may kill the launch process tree after native startup crashes.
  // Only this intentional crash permits missing callbacks; no child may survive.
  const crashedBackend = events("backend").filter((item) => item.event === "activate" && !beforeCrash.has(item.pid));
  for (const activation of crashedBackend) {
    const deadline = Date.now() + 10_000;
    while (processAlive(activation.pid) && Date.now() < deadline) await delay(100);
    assert.equal(processAlive(activation.pid), false, `crashed backend PID ${activation.pid} reclaimed`);
    interruptedBackendPids.add(activation.pid);
  }
  const crashMarker = JSON.parse(readFileSync(path.join(root, "profile/extension-desktop-loading.json"), "utf8"));
  assert.equal(crashMarker.digest, createHash("sha256").update(readFileSync(path.join(root, "packages/crash.csext"))).digest("hex"));
  assert.equal(Number.isInteger(crashMarker.generation), true);
  await launch();
  await manager();
  await page.getByText(/Previous startup interrupted/).waitFor();
  await page.locator(".extension-item").filter({ hasText: "Interrupted startup qualification" }).screenshot({ path: path.join(root, "interrupted-startup-recovery.png") });
  await action("Interrupted startup qualification", "停用", "Disable");
  record("interrupted-desktop-startup-is-skipped-on-next-boot", { markerPresent: true, recovered: true,
    reclaimedBackendPids: [...interruptedBackendPids], forcedCrashCleanupGuaranteed: false, interruption });
  await close();
  report.result = "pass";
} catch (error) {
  report.result = "fail";
  report.failures.push(String(error.stack ?? error));
  if (page && !page.isClosed()) await page.screenshot({ path: path.join(root, "failure.png") }).catch(() => {});
  process.exitCode = 1;
} finally {
  await close().catch((error) => { report.failures.push(`shutdown: ${error}`); report.result = "fail"; process.exitCode = 1; });
  report.finishedAt = new Date().toISOString();
  save();
  console.log(`REPORT ${path.join(root, "report.json")}`);
}
