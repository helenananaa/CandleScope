import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";

const [executable, packagePath, driver, output] = process.argv.slice(2).map((value) => path.resolve(value));
const { _electron } = createRequire(import.meta.url)(driver);
const profile = path.join(output, "desktop-profile");
const pluginId = "candlescope.aho-corasick";
const digest = "sha256:" + createHash("sha256").update(await readFile(packagePath)).digest("hex");
const env = {
  ...process.env,
  CANDLESCOPE_RUNTIME_MODE: "LIVE",
  CANDLESCOPE_DESKTOP_USER_DATA: profile,
  CANDLESCOPE_DESKTOP_UI_PORT: "0",
  CANDLESCOPE_DESKTOP_BACKEND_PORT: "0",
  CANDLESCOPE_LOCAL_DATA_DIR: path.join(profile, "local-data"),
  CANDLESCOPE_PLUGIN_PLATFORM_V2_ROOT: path.join(profile, "plugins"),
  CANDLESCOPE_PLUGIN_PLATFORM_V2_ENABLED: "1",
  CANDLE_DATA_DIR: path.join(profile, "data"),
};
for (const key of [
  "ELECTRON_RUN_AS_NODE", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV",
  "CANDLESCOPE_DESKTOP_URL", "CANDLESCOPE_DESKTOP_SKIP_SIDECAR",
  "CANDLESCOPE_DESKTOP_SIDECAR_COMMAND_JSON", "CANDLESCOPE_PYTHON",
]) delete env[key];

async function launch() {
  const app = await _electron.launch({ executablePath: executable, env, timeout: 120_000 });
  try {
    const page = await app.firstWindow({ timeout: 90_000 });
    await page.waitForURL((url) => url.protocol === "http:" && url.hostname === "127.0.0.1", {
      waitUntil: "load", timeout: 90_000,
    });
    const identity = await app.evaluate(({ app }) => ({
      packaged: app.isPackaged, resources: process.resourcesPath, profile: app.getPath("userData"),
    }));
    assert.equal(identity.packaged, true);
    assert.equal(path.resolve(identity.profile), profile);
    const bootstrap = await page.evaluate(() => window.candlescopeDesktop.getBootstrap());
    const command = bootstrap.sidecar.command.replace(/^\\\\\?\\/, "");
    const bundledPython = path.relative(path.join(identity.resources, "python-runtime"), command);
    assert.ok(!path.isAbsolute(bundledPython) && !bundledPython.startsWith(".."));
    assert.equal(path.basename(bundledPython).toLowerCase(), "python.exe");
    assert.ok(bootstrap.sidecar.running);
    return { app, page, health: bootstrap.sidecar.healthUrl };
  } catch (error) {
    await app.close().catch(() => {});
    throw error;
  }
}

async function search(page) {
  await page.locator("[data-plugin-command-palette]").first().click();
  const palette = page.getByTestId("plugin-command-palette");
  await palette.getByRole("button", { name: /Run aho-corasick Search/ }).click();
  await palette.locator("form button[type=submit]").click();
  const output = JSON.parse(await palette.locator(".plugin-unified-command-result").innerText());
  assert.equal(output.schemaVersion, "candlescope.aho-corasick.matches/1");
  assert.equal(output.matches.length, 6);
  assert.ok(output.matches.some((match) => match.patternIndex === 3 && match.endByte - match.startByte === 6));
  return output;
}

let running;
const report = { packageSha256: digest, platform: process.platform, arch: process.arch };
try {
  assert.equal(process.platform, "win32");
  running = await launch();
  const first = running.page;
  await first.locator(".settings-btn").first().click();
  await first.locator(".st-nav-item").filter({ hasText: /^\s*(Plugins|插件与扩展)\s*$/ }).click();
  await first.locator(".pc-toolbar-actions").getByRole("button", { name: /Install|安装/ }).click();
  await first.locator(".extension-manager input[type=file]").first().setInputFiles(packagePath);
  const review = first.locator(".extension-review");
  await review.locator("input[type=checkbox]").check();
  await review.getByRole("button", { name: /Enable this version|确认启用/ }).click();
  await review.waitFor({ state: "detached" });
  await first.locator(".st-content-header button").click();
  const initial = await search(first);
  report.installedSearch = "passed";
  const health = running.health;
  await running.app.close();
  running = undefined;
  let exited = false;
  for (let attempt = 0; attempt < 30; attempt += 1) {
    try { await fetch(health, { signal: AbortSignal.timeout(500) }); }
    catch { exited = true; break; }
    await delay(200);
  }
  assert.equal(exited, true);
  running = await launch();
  assert.deepEqual(await search(running.page), initial);
  report.restartSearch = "passed";
  report.result = "passed";
} catch (error) {
  report.result = "failed";
  report.error = error.stack;
  if (running) {
    await running.page.screenshot({ path: path.join(output, "installed-failure.png") }).catch(() => {});
  }
  throw error;
} finally {
  await writeFile(path.join(output, "installed.json"), JSON.stringify(report, null, 2) + "\n");
  if (running) await running.app.close();
}
