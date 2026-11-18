const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const { createHash, randomUUID } = require("node:crypto");
const { execFileSync } = require("node:child_process");
const { setTimeout: delay } = require("node:timers/promises");
const { _electron } = require(process.env.CANDLESCOPE_QA_PLAYWRIGHT || "playwright-core");

const [appPath, qaPath, receiptPath] = process.argv.slice(2);
const api = "/api/v2/plugins";
const market = api + "/manage/marketplace";
const unified = api + "/manage/unified";
const sha = bytes => "sha256:" + createHash("sha256").update(bytes).digest("hex");
const windows = process.platform === "win32";
const proc = () => (windows
  ? execFileSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command",
    "Get-CimInstance Win32_Process | ForEach-Object { '{0} {1}' -f $_.ProcessId,$_.ParentProcessId }"],
  { encoding: "utf8" })
  : execFileSync("ps", ["-axo", "pid=,ppid="], { encoding: "utf8" }))
  .trim().split("\n").map(row => row.trim().split(/\s+/).map(Number));
const read = async file => JSON.parse(await fs.readFile(file, "utf8"));

async function main() {
  const qa = await fs.realpath(qaPath);
  const profile = path.join(qa, "profile");
  const home = path.join(qa, "home");
  await fs.mkdir(home, { recursive: true });
  const fixtures = await read(path.join(qa, "fixtures.json"));
  const resources = windows ? path.join(path.dirname(appPath), "resources")
    : path.join(appPath, "Contents", "Resources");
  const executable = windows ? appPath : path.join(appPath, "Contents", "MacOS", "CandleScope");
  if (!windows) execFileSync("codesign", ["--verify", "--deep", "--strict", appPath]);
  const receipt = {
    platform: process.platform, architecture: process.arch, signatureVerified: windows ? null : true,
    appAsar: sha(await fs.readFile(path.join(resources, "app.asar"))),
    fixtures, sessions: [],
  };
  const env = {
    ...process.env,
    HOME: home, TMPDIR: qa,
    CANDLESCOPE_RUNTIME_MODE: "LIVE", CANDLESCOPE_DESKTOP_USER_DATA: profile,
    CANDLESCOPE_DESKTOP_UI_PORT: "0", CANDLESCOPE_DESKTOP_BACKEND_PORT: "0",
    CANDLESCOPE_PLUGIN_PLATFORM_V2_ROOT: path.join(profile, "plugins"),
    CANDLESCOPE_PLUGIN_PLATFORM_V2_MARKETPLACE_ENABLED: "1",
    CANDLESCOPE_PLUGIN_PLATFORM_V2_MARKETPLACE_ROOTS: path.join(qa, "roots.json"),
    CANDLE_DATA_DIR: path.join(profile, "data"),
    CANDLESCOPE_LOCAL_DATA_DIR: path.join(profile, "library"),
    HTTP_PROXY: "http://127.0.0.1:9", HTTPS_PROXY: "http://127.0.0.1:9",
    ALL_PROXY: "http://127.0.0.1:9", NO_PROXY: "127.0.0.1,localhost",
  };
  for (const key of [
    "ELECTRON_RUN_AS_NODE", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV",
    "CANDLESCOPE_DESKTOP_URL", "CANDLESCOPE_DESKTOP_SKIP_SIDECAR",
    "CANDLESCOPE_DESKTOP_SIDECAR_COMMAND_JSON", "CANDLESCOPE_PYTHON",
  ]) delete env[key];
  const record = () => fs.writeFile(receiptPath, JSON.stringify(receipt, null, 2) + "\n");
  let migratedStorage;
  let healthyGeneration;
  let legacyExport;
  const settings = /^Settings$|^设置$/;
  const discover = /^Discover$|^发现插件$/;
  const pluginSettings = /^(?:Plugins|Plugin center|插件与扩展|插件中心)$/i;

  async function inSession(name, run) {
    const result = { name };
    receipt.sessions.push(result);
    let electron;
    const pids = new Set();
    try {
      electron = await _electron.launch({
        executablePath: executable,
        args: ["--lang=en-US"],
        env,
        timeout: 120000,
      });
      const identity = await electron.evaluate(({ app }) => ({
        packaged: app.isPackaged, pid: process.pid, userData: app.getPath("userData"),
        electron: process.versions.electron,
      }));
      pids.add(identity.pid);
      assert.equal(identity.packaged, true);
      assert.equal(path.resolve(identity.userData), profile);
      result.electron = identity.electron;
      const page = await electron.firstWindow({ timeout: 90000 });
      await page.waitForURL(url => url.protocol === "http:" && url.hostname === "127.0.0.1", {
        waitUntil: "load", timeout: 90000,
      });
      const bootstrap = await page.evaluate(() => window.candlescopeDesktop.getBootstrap());
      const command = bootstrap.sidecar.command.replace(/^\\\\\?\\/, "");
      const bundledPython = path.relative(path.join(resources, "python-runtime"), command);
      assert.ok(bundledPython && !path.isAbsolute(bundledPython) && !bundledPython.startsWith(".."));
      const connection = await page.evaluate(() => ({
        backend: new URL(window.candlescopeDesktop.apiBase).origin,
        session: window.candlescopeDesktop.getPluginManagementSession(),
        origin: location.origin,
      }));
      const request = async (route, { body, bytes, media, hash, status = 200 } = {}) => {
        const headers = {
          Origin: connection.origin,
          "X-CandleScope-Plugin-Session": connection.session.sessionToken,
        };
        const post = bytes !== undefined || body !== undefined;
        if (post) Object.assign(headers, {
          "Content-Type": media || "application/json",
          "X-CandleScope-CSRF": connection.session.csrfToken,
          "X-CandleScope-User-Action": "marketplace-qa-" + randomUUID(),
        });
        if (hash) headers["X-CandleScope-Bundle-SHA256"] = hash;
        const resp = await fetch(connection.backend + route, {
          method: post ? "POST" : "GET", headers,
          body: post ? bytes ?? JSON.stringify(body) : undefined,
        });
        const payload = await resp.json();
        assert.equal(resp.status, status, JSON.stringify(payload).slice(0, 1300));
        return payload;
      };
      const health = await request("/health");
      assert.equal(health.runtime_mode, "LIVE");
      result.pluginPlatformStarted = health.plugin_platform_v2?.started === true;
      assert.equal(result.pluginPlatformStarted, true, JSON.stringify(health.plugin_plane));
      assert.ok(health.unified_plugins?.executors_attached, "unified executors did not start");
      const control = {
        page, result, request,
        catalog: () => request(unified),
        oldCatalog: () => request(api + "/catalog"),
        invokeLegacy: () => request(api + "/manage/commands/" + fixtures.legacy.id + ".hello/invoke",
          { body: { input: { name: "Marketplace" } } }),
        index: async sequence => request(`${market}/${fixtures.marketplaceId}/index`, {
          bytes: await fs.readFile(path.join(qa, `index-${sequence}.json`)),
        }),
        select: async id => request(unified + "/change", { body: {
          action: "select-appearance", kind: "theme", id,
          revision: (await request(unified)).revision,
        } }),
        color: async color => {
          await page.waitForFunction(expected =>
            getComputedStyle(document.documentElement).getPropertyValue("--bg-primary").trim() === expected,
          color, { timeout: 30000 });
          return page.evaluate(() => ({
            theme: document.documentElement.dataset.extensionTheme ?? null,
            background: getComputedStyle(document.documentElement).getPropertyValue("--bg-primary").trim(),
          }));
        },
      };
      control.openMarket = async () => {
        if (!(await page.getByTestId("plugin-manager").isVisible())) {
          if (!(await page.locator(".st-sidebar").isVisible())) {
            await page.getByRole("button", { name: settings }).first().click({ timeout: 30000 });
          }
          await page.locator(".st-sidebar-nav").getByRole("button", { name: pluginSettings }).click();
        }
        await page.getByTestId("plugin-manager").getByRole("tab", { name: discover }).click();
        await page.locator("[data-plugin-marketplace]").waitFor();
      };
      control.activate = async (release, { failure = false, migration = false, checkCancel = false } = {}) => {
        // Seed the signed artifact via the production guarded upload. The
        // renderer subsequently downloads it from the verified content cache.
        const bytes = await fs.readFile(path.join(qa, "artifacts", release.file));
        assert.equal(sha(bytes), release.sha256);
        await request(`${market}/${release.id}/${release.version}/artifact`, {
          bytes, media: "application/vnd.candlescope.plugin+zip", hash: release.sha256,
        });
        const card = page.locator(`[data-marketplace-plugin="${release.id}"]`);
        await page.getByTestId("plugin-manager").getByRole("button", { name: /^Refresh$|^刷新$/ }).first().click();
        await card.locator(".plugin-marketplace-title").getByText(`${release.version} · MIT`, { exact: true }).waitFor();
        const done = suffix => page.waitForResponse(response =>
          new URL(response.url()).pathname === `${market}/${release.id}/${suffix}`
          && response.request().method() === "POST",
        { timeout: 30000 });
        const button = action => page.locator(`[data-marketplace-${action}="${release.id}"]`);
        let response = done("prepare");
        await button("prepare").click();
        const prepared = await response;
        assert.equal(prepared.status(), 200, await prepared.text());
        const candidate = (await prepared.json()).candidate;
        assert.equal(candidate.bundleSha256, release.sha256);
        assert.equal(candidate.compatibility.cacheReuse, true);
        response = done("apply");
        await button("apply").click();
        assert.equal((await response).status(), 200);
        await button("activate").click();
        const dialog = page.getByRole("alertdialog");
        await dialog.waitFor();
        const review = await dialog.innerText();
        assert.ok(review.includes(release.sha256) && review.includes(release.version));
        if (migration) assert.match(review, /previous version|旧版/);
        if (checkCancel) {
          await dialog.getByRole("button", { name: /^Cancel$|^取消$/ }).click();
          await dialog.waitFor({ state: "hidden" });
          assert.equal(plugin(await control.catalog(), release.id), undefined);
          await button("activate").click();
          await dialog.waitFor();
          result.cancelLeftInactive = true;
        }
        response = done("activate");
        await dialog.getByRole("button", { name: /Activate & observe|激活并观察/ }).click();
        const activated = await response;
        const payload = await activated.json();
        assert.equal(activated.status(), failure ? 409 : 200, JSON.stringify(payload));
        const phase = failure ? "rolled-back" : "active";
        await page.locator(`[data-marketplace-plugin="${release.id}"] [data-marketplace-candidate-phase="${phase}"]`)
          .waitFor({ timeout: 30000 });
        assert.equal((await request(market + "/status")).candidates.find(item => item.pluginId === release.id).phase, phase);
        return payload;
      };
      await run(control);
    } catch (err) {
      result.failure = String(err);
      throw err;
    } finally {
      try {
        if (electron) {
          const tree = proc();
          for (let level = 0; level < 10; level++) {
            for (const [pid, parent] of tree) if (pids.has(parent)) pids.add(pid);
          }
          await electron.close();
          for (let attempt = 0; attempt < 10; attempt++) {
            result.remainingOwnedProcesses = proc().filter(([pid]) => pids.has(pid)).map(([pid]) => pid);
            if (!result.remainingOwnedProcesses.length) break;
            await delay(250);
          }
          assert.deepEqual(result.remainingOwnedProcesses, []);
        }
      } finally {
        await record();
      }
    }
  }

  function plugin(catalog, id) {
    return catalog.plugins.find(item => item.id === id);
  }
  async function preserved() {
    for (const [relative, expected] of Object.entries(fixtures.sources)) {
      assert.equal(sha(await fs.readFile(path.join(profile, relative))), expected, relative);
    }
  }

  await inSession("install, update and migrate", async q => {
    await q.openMarket();
    const old = plugin(await q.oldCatalog(), fixtures.legacy.id);
    assert.equal(old.version, fixtures.legacy.version);
    q.result.legacyAvailable = old.available;
    assert.equal(old.available, windows, JSON.stringify(old));
    if (windows) assert.equal((await q.invokeLegacy()).result.message, "Hello, Marketplace!");
    const initial = await q.activate(fixtures.initial, { checkCancel: true });
    q.result.installGeneration = initial.activation.generation;
    await q.select(fixtures.initial.id);
    q.result.installedWindow = await q.color(fixtures.initial.color);
    await q.index(2);
    // Navigating back refreshes the catalog normally after the fixture index import.
    await q.page.getByTestId("plugin-manager").getByRole("tab", { name: /My plugins|我的插件/ }).click();
    await q.openMarket();
    const upgraded = await q.activate(fixtures.upgrade);
    healthyGeneration = upgraded.activation.generation;
    assert.ok(healthyGeneration > initial.activation.generation);
    q.result.upgradedWindow = await q.color(fixtures.upgrade.color);
    const migrated = await q.activate(fixtures.successor, { migration: true });
    q.result.migrationGeneration = migrated.activation.migration.generation;
    await q.select(fixtures.successor.id);
    q.result.migratedWindow = await q.color(fixtures.successor.color);
    assert.equal(plugin(await q.oldCatalog(), fixtures.legacy.id), undefined);
    migratedStorage = path.join(profile, "plugins", "unified", "marketplace-private",
      fixtures.legacy.id, String(migrated.activation.migration.generation));
    legacyExport = path.join(migratedStorage, "platform-v2");
    assert.deepEqual((await read(path.join(legacyExport, "settings.json"))).records.map(item => item.value),
      [{ density: "compact" }]);
    assert.deepEqual((await read(path.join(legacyExport, "host-storage.json"))).kv,
      [{ key: "bookmark", value: { row: 7 } }]);
    const sandboxCopy = await fs.readFile(path.join(legacyExport, "sandbox", "state.bin"));
    assert.equal(sandboxCopy.toString("utf8"), "original sandbox data\n");
    q.result.copiedData = { settingsRecords: 1, hostKeys: ["bookmark"], sandboxFileSha256: sha(sandboxCopy) };
    await fs.writeFile(path.join(migratedStorage, "qa-new-data.txt"), "new version data\n");
    await preserved();
    q.result.legacyFilesByteIdentical = true;
  });

  await inSession("restart, manual and health rollback", async q => {
    q.result.restartedWindow = await q.color(fixtures.successor.color);
    assert.equal(plugin(await q.oldCatalog(), fixtures.legacy.id), undefined);
    assert.equal(await fs.readFile(path.join(migratedStorage, "qa-new-data.txt"), "utf8"), "new version data\n");
    await q.openMarket();
    await q.page.locator(`[data-marketplace-rollback="${fixtures.legacy.id}"]`).click();
    const dialog = q.page.getByRole("alertdialog");
    assert.match(await dialog.innerText(), new RegExp(fixtures.legacy.id));
    const response = q.page.waitForResponse(resp => new URL(resp.url()).pathname ===
      `${market}/${fixtures.legacy.id}/rollback-migration`, { timeout: 30000 });
    await dialog.getByRole("button", { name: /Roll back|回滚/i }).click();
    const restored = await response;
    q.result.manualRollback = await restored.json();
    assert.equal(restored.status(), 200, JSON.stringify(q.result.manualRollback));
    assert.deepEqual(q.result.manualRollback, { restoredVersion: fixtures.legacy.version, runtimeReady: windows });
    assert.equal(plugin(await q.catalog(), fixtures.legacy.id), undefined);
    assert.equal(plugin(await q.oldCatalog(), fixtures.legacy.id).version, fixtures.legacy.version);
    if (windows) {
      assert.equal((await q.invokeLegacy()).result.message, "Hello, Marketplace!");
      q.result.legacyCommandAfterRollback = "passed";
    }
    await q.page.waitForFunction(() => !document.documentElement.dataset.extensionTheme);
    q.result.migratedAppearanceRemoved = true;
    await preserved();
    await q.select(fixtures.upgrade.id);
    await q.color(fixtures.upgrade.color);
    await q.index(3);
    await q.page.getByTestId("plugin-manager").getByRole("tab", { name: /My plugins|我的插件/ }).click();
    await q.openMarket();
    const failure = await q.activate(fixtures.failed, { failure: true });
    assert.equal(failure.detail.code, "PLUGIN_MARKETPLACE_HEALTH_ROLLBACK");
    assert.equal(failure.detail.details.restoredVersion, fixtures.upgrade.version);
    assert.equal(failure.detail.details.runtimeReady, true);
    const observed = plugin(await q.catalog(), fixtures.upgrade.id);
    assert.equal(observed.desired.packageSha256, fixtures.upgrade.sha256);
    assert.ok(observed.desired.generation > healthyGeneration);
    q.result.healthRollback = { ...failure.detail.details, restoredGeneration: observed.desired.generation };
    q.result.rolledBackWindow = await q.color(fixtures.upgrade.color);
  });

  await inSession("restart after both rollbacks", async q => {
    q.result.finalWindow = await q.color(fixtures.upgrade.color);
    const theme = plugin(await q.catalog(), fixtures.upgrade.id);
    assert.equal(theme.desired.packageSha256, fixtures.upgrade.sha256);
    assert.ok(theme.entries.find(item => item.id === "theme").observed.some(item => item.state === "ready"));
    assert.equal(plugin(await q.catalog(), fixtures.legacy.id), undefined);
    assert.equal(plugin(await q.oldCatalog(), fixtures.legacy.id).version, fixtures.legacy.version);
    if (windows) {
      assert.equal((await q.invokeLegacy()).result.message, "Hello, Marketplace!");
      q.result.legacyCommandAfterRestart = "passed";
    }
    assert.equal(await fs.readFile(path.join(migratedStorage, "qa-new-data.txt"), "utf8"), "new version data\n");
    await preserved();
    q.result.bothVersionsDataPreserved = true;
  });
  receipt.ok = true;
  await record();
}
main().catch(err => { console.error(err); process.exitCode = 1; });
