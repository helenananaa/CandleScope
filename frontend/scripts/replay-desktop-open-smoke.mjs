/** Verify a packaged replay creation, deletion, stale draft recovery and reopening. */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync, readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i < 0 ? fallback : process.argv[i + 1]; };
assert.ok(arg("--executable"), "Pass the packaged CandleScope executable");
const executable = path.resolve(arg("--executable"));
const output = path.resolve(arg("--out", path.join(repo, "output/playwright/replay-desktop-open")));
mkdirSync(output, { recursive: true });
const root = mkdtempSync(path.join(output, "run-"));
const profile = path.join(root, "profile");
const data = path.join(profile, "data");
mkdirSync(data, { recursive: true });
const require = createRequire(import.meta.url);
const { _electron } = require(arg("--playwright-module", "playwright-core"));
const env = { ...process.env, CANDLESCOPE_DESKTOP_USER_DATA: profile,
  CANDLE_DATA_DIR: data, KLINES_DB_PATH: path.join(data, "candlescope.db"), REPLAY_DB_PATH: path.join(data, "replay.db"),
  REPLAY_HISTORY_ARCHIVE_DIR: path.join(data, "replay-history"), REPLAY_HISTORY_ORIGIN_URI: " ",
  REPLAY_ENABLED: "1", CANDLESCOPE_DESKTOP_UI_PORT: "0", CANDLESCOPE_DESKTOP_BACKEND_PORT: "0",
  CANDLESCOPE_PLUGIN_PLATFORM_V2_ROOT: path.join(root, "plugins"),
  CANDLESCOPE_LOCAL_DATA_DIR: path.join(root, "local-data"),
};
for (const key of ["ELECTRON_RUN_AS_NODE", "PYTHONPATH", "CANDLESCOPE_DESKTOP_URL", "CANDLESCOPE_DESKTOP_SKIP_SIDECAR",
  "CANDLESCOPE_DESKTOP_SIDECAR_COMMAND_JSON", "CANDLESCOPE_PYTHON"]) delete env[key];
const seed = spawnSync(arg("--python", path.join(repo, ".venv/Scripts/python.exe")), ["-c",
  "import os, sqlite3; import scripts.replay_smoke_fixture as f; f._seed_klines(); db=sqlite3.connect(os.environ['KLINES_DB_PATH']); db.execute(\"UPDATE klines SET source='backfill'\"); db.commit(); db.close(); f._seed_replay_history_archive()"],
{ cwd: path.join(repo, "backend"), env, encoding: "utf8", windowsHide: true });
assert.equal(seed.status, 0, seed.stderr);
const report = { schema: "candlescope.replay-desktop-open/1", executable, root, syntheticData: true,
  startedAt: new Date().toISOString(), appAsarSha256: createHash("sha256").update(readFileSync(path.join(path.dirname(executable), "resources/app.asar"))).digest("hex"),
  phases: [], exceptions: [], result: "running" };
const save = () => writeFileSync(path.join(root, "report.json"), JSON.stringify(report, null, 2));
const record = (name, evidence) => { report.phases.push({ name, evidence }); save(); console.log(`PASS ${name}`); };
let app, page;
save();
try {
  app = await _electron.launch({ executablePath: executable, env, timeout: 90_000 });
  page = await app.firstWindow({ timeout: 90_000 });
  page.setDefaultTimeout(30_000);
  const identity = await app.evaluate(({ app }) => ({ packaged: app.isPackaged, userData: app.getPath("userData") }));
  assert.equal(identity.packaged, true);
  assert.equal(path.resolve(identity.userData), profile);
  await page.getByRole("button", { name: /扩展恢复|Extension recovery/ }).waitFor();
  const origin = new URL(page.url()).origin;
  await page.goto(`${origin}/replay.html`);
  page.on("pageerror", error => { report.exceptions.push(error.stack); save(); });
  const submissions = [];
  page.on("request", request => {
    if (request.method() === "POST" && request.url().endsWith("/data-preparations/replay")) submissions.push(request.postDataJSON());
  });
  await page.getByRole("button", { name: "新建训练", exact: true }).click();
  await page.getByRole("textbox", { name: "商品", exact: true }).fill("BTCUSDT");
  await page.getByRole("textbox", { name: "开始时间（UTC）", exact: true }).fill("2023-11-15T12:00");
  // Exercise the production 4h launch context, using the same persisted draft
  // that users retain after closing a preparation observer.
  await page.evaluate(() => {
    for (const key of Object.keys(localStorage).filter(key => key.startsWith("candlescope.replay-create.v1:"))) {
      const saved = JSON.parse(localStorage.getItem(key)); saved.draft.displayInterval = "4h";
      saved.draft.indicatorWarmupBars = 2;
      localStorage.setItem(key, JSON.stringify(saved));
    }
  });
  await page.reload();
  await page.getByRole("button", { name: "新建训练", exact: true }).click();
  await page.getByRole("button", { name: "确认时间并创建训练", exact: true }).click();
  await page.waitForFunction(() => Object.values(localStorage).some(text => {
    try { return JSON.parse(text)?.submission?.key; } catch { return false; }
  }));
  const pendingDrafts = await page.evaluate(() => Object.fromEntries(Object.keys(localStorage)
    .filter(key => key.startsWith("candlescope.replay-create.v1:")).map(key => [key, localStorage.getItem(key)])));
  const ready = async () => {
    await page.locator('[data-replay-session-state="PAUSED"][data-replay-viewer-state-ready="true"]').waitFor({ timeout: 90_000 });
    await page.waitForFunction(() => document.querySelector('[data-replay-cell-bars]')?.getAttribute('data-replay-cell-bars') > 0);
    assert.equal(await page.getByRole("heading", { name: "无法打开回放" }).count(), 0);
    assert.equal(report.exceptions.length, 0, report.exceptions.join("\n"));
  };
  await ready();
  const firstRun = new URL(page.url()).searchParams.get("run");
  assert.ok(firstRun);
  assert.equal(submissions[0].display_interval, "4h");
  await page.screenshot({ path: path.join(root, "first-open.png") });
  record("create-and-open-4h", { runId: firstRun, identity });
  // Use the real deletion UI; original completed job receipts survive it.
  await page.getByRole("button", { name: "存档大厅", exact: true }).click();
  await page.getByRole("button", { name: "新建训练", exact: true }).waitFor();
  const card = page.locator(".training-hub-card").filter({ hasText: "BTCUSDT" });
  await card.getByRole("button", { name: /删除/ }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: /确认.*删除/ }).click();
  await card.waitFor({ state: "hidden" });
  record("delete-prepared-run", { runId: firstRun });
  await page.evaluate(values => { for (const [key, value] of Object.entries(values)) localStorage.setItem(key, value); }, pendingDrafts);
  await page.reload();
  await page.getByRole("button", { name: "新建训练", exact: true }).click();
  await page.getByRole("button", { name: "确认时间并创建训练", exact: true }).click();
  await ready();
  const secondRun = new URL(page.url()).searchParams.get("run");
  assert.notEqual(secondRun, firstRun);
  assert.equal(submissions.length, 3);
  assert.equal(submissions[0].idempotency_key, submissions[1].idempotency_key);
  assert.notEqual(submissions[1].idempotency_key, submissions[2].idempotency_key);
  record("recover-deleted-result-from-saved-draft", { firstRun, secondRun, submissions: submissions.length });
  const cursor = await page.locator('[data-replay-cursor-ms]').getAttribute('data-replay-cursor-ms');
  await page.getByRole("button", { name: "下一根 1m", exact: true }).click();
  await page.waitForFunction(before => Number(document.querySelector('[data-replay-cursor-ms]')?.getAttribute('data-replay-cursor-ms')) > Number(before), cursor);
  await page.reload(); await ready();
  record("advance-and-reload", { runId: secondRun });
  await page.getByRole("button", { name: "存档大厅", exact: true }).click();
  await page.locator(".training-hub-card").getByRole("button", { name: "继续训练", exact: true }).click();
  await ready();
  await page.screenshot({ path: path.join(root, "reopened.png") });
  record("return-to-hub-and-reopen", { runId: secondRun });
  await app.close();
  app = await _electron.launch({ executablePath: executable, env, timeout: 90_000 });
  page = await app.firstWindow({ timeout: 90_000 });
  page.setDefaultTimeout(30_000);
  page.on("pageerror", error => { report.exceptions.push(error.stack); save(); });
  await page.getByRole("button", { name: /扩展恢复|Extension recovery/ }).waitFor();
  await page.goto(`${new URL(page.url()).origin}/replay.html`);
  await page.locator(".training-hub-card").getByRole("button", { name: "继续训练", exact: true }).click();
  await ready();
  await page.screenshot({ path: path.join(root, "restarted.png") });
  record("restart-production-and-reopen", { runId: secondRun });
  await page.getByRole("button", { name: "4H", exact: true }).click();
  await page.locator('[data-replay-cell-interval="4h"][data-replay-cell-error=""]').waitFor({ state: "attached" });
  await ready();
  await page.screenshot({ path: path.join(root, "chart-4h.png") });
  record("switch-chart-to-4h", { runId: secondRun });
  report.result = "passed";
} catch (error) {
  report.result = "failed"; report.failure = error.stack;
  if (page && !page.isClosed()) {
    writeFileSync(path.join(root, "failure-page.txt"), await page.locator("body").ariaSnapshot().catch(() => "unavailable"));
    await page.screenshot({ path: path.join(root, "failure.png") }).catch(() => {});
  }
  process.exitCode = 1;
} finally {
  save();
  if (app) await app.close();
  console.log(path.join(root, "report.json"));
}
