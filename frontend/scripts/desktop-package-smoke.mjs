/** Launch the shipped app from a relocated path, with no development Python. */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const arg = (name) => process.argv[process.argv.indexOf(name) + 1];
assert.ok(process.argv.includes("--executable"), "Pass --executable");
assert.ok(process.argv.includes("--playwright-module"), "Pass --playwright-module");
const executable = path.resolve(arg("--executable"));
const output = path.resolve(arg("--out"));
const profile = path.join(output, "profile");
await mkdir(profile, { recursive: true });
const { _electron } = createRequire(import.meta.url)(arg("--playwright-module"));
const env = { ...process.env,
  CANDLESCOPE_DESKTOP_USER_DATA: profile,
  CANDLE_DATA_DIR: path.join(profile, "data"),
  CANDLESCOPE_DESKTOP_UI_PORT: "0", CANDLESCOPE_DESKTOP_BACKEND_PORT: "0",
  CANDLESCOPE_PLUGIN_PLATFORM_V2_ROOT: path.join(profile, "plugins"),
  CANDLESCOPE_LOCAL_DATA_DIR: path.join(profile, "local-data"),
};
for (const key of ["ELECTRON_RUN_AS_NODE", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV",
  "CANDLESCOPE_DESKTOP_URL", "CANDLESCOPE_DESKTOP_SKIP_SIDECAR",
  "CANDLESCOPE_DESKTOP_SIDECAR_COMMAND_JSON", "CANDLESCOPE_PYTHON"]) delete env[key];
const report = { result: "running", executable, platform: process.platform, arch: process.arch, launches: [] };
let app;
const save = () => writeFile(path.join(output, "report.json"), JSON.stringify(report, null, 2) + "\n");
async function phase(name, action, timeout = 60_000) {
  report.phase = name;
  await save();
  console.log(`START ${name}`);
  let timer;
  try {
    const value = await Promise.race([
      action(),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`Timed out: ${name}`)), timeout); }),
    ]);
    console.log(`PASS ${name}`);
    return value;
  } finally {
    clearTimeout(timer);
  }
}
try {
  for (let attempt = 0; attempt < 2; attempt += 1) {
    app = await phase(`launch-${attempt + 1}`, () => _electron.launch({ executablePath: executable, env, timeout: 120_000 }), 125_000);
    const page = await phase("first-window", () => app.firstWindow({ timeout: 120_000 }), 125_000);
    page.setDefaultTimeout(30_000);
    page.setDefaultNavigationTimeout(60_000);
    const identity = await phase("app-identity", () => app.evaluate(({ app }) => ({ packaged: app.isPackaged, userData: app.getPath("userData"), resources: process.resourcesPath })));
    assert.equal(identity.packaged, true);
    assert.equal(path.resolve(identity.userData), profile);
    await page.waitForFunction(() => Boolean(window.candlescopeDesktop), null, { timeout: 30_000 });
    const bootstrap = await phase("desktop-bootstrap", () => page.evaluate(() => window.candlescopeDesktop.getBootstrap()));
    assert.equal(bootstrap.sidecar.running, true);
    assert.ok(bootstrap.sidecar.command.startsWith(path.join(identity.resources, "python-runtime")));
    const health = await fetch(bootstrap.sidecar.healthUrl, { signal: AbortSignal.timeout(10_000) });
    assert.equal(health.status, 200);
    assert.ok((await health.json()).desktop_instance_id);
    const pages = [];
    const origin = new URL(page.url()).origin;
    for (const entry of ["index.html", "replay.html", "strategy.html"]) {
      await phase(`page-${entry}`, async () => {
        await page.goto(`${origin}/${entry}`);
        await page.waitForFunction(() => document.title.includes("CandleScope") && document.body.innerText.trim().length > 30);
      }, 95_000);
      assert.equal(await page.locator("vite-error-overlay").count(), 0);
      pages.push({ entry, title: await page.title() });
    }
    await page.screenshot({ path: path.join(output, `launch-${attempt + 1}.png`) });
    report.launches.push({ identity, python: bootstrap.sidecar.command, health: "passed", pages });
    await phase("graceful-close", () => app.close(), 45_000);
    app = null;
  }
  report.result = "passed";
} catch (error) {
  report.result = "failed";
  report.error = error.stack;
  process.exitCode = 1;
} finally {
  // Save diagnostics before cleanup: a hung application must not hide its failure.
  await save();
  if (app) {
    let timer;
    await Promise.race([
      app.close().catch(() => {}),
      new Promise(resolve => { timer = setTimeout(() => { app.process().kill("SIGKILL"); resolve(); }, 10_000); }),
    ]);
    clearTimeout(timer);
  }
  console.log(JSON.stringify(report, null, 2));
}
