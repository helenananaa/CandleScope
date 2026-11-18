const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { createHash, randomUUID } = require("node:crypto");
const { execFileSync } = require("node:child_process");
const { _electron } = require(process.env.CANDLESCOPE_QA_PLAYWRIGHT || "playwright-core");

const application = process.argv[2];
const receiptPath = process.argv[3];
const candidateUpgrade = process.argv[4];
const pineId = "candlescope.pine-compat";
const originPath = "/api/v1/backtests/native";
const windows = process.platform === "win32";
const res = windows ? path.join(path.dirname(application), "resources")
  : path.join(application, "Contents", "Resources");
const executable = windows ? application : path.join(application, "Contents", "MacOS", "CandleScope");
const versionDescriptor = path.join(res, "python-runtime", "plugins", "unified-pine.json");
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const hash = data => createHash("sha256").update(data).digest("hex");
const children = () => (windows
  ? execFileSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command",
    "Get-CimInstance Win32_Process | ForEach-Object { '{0} {1}' -f $_.ProcessId,$_.ParentProcessId }"],
  { encoding: "utf8" })
  : execFileSync("ps", ["-axo", "pid=,ppid="], { encoding: "utf8" }))
  .trim().split("\n").map(line => line.trim().split(/\s+/).map(Number));

(async () => {
  const qaRoot = await fs.mkdtemp(path.join(os.tmpdir(), "candlescope-pine351-native-"));
  const profile = path.join(qaRoot, "profile");
  const receipt = { profile, platform: process.platform, arch: process.arch, phases: [] };
  const save = () => fs.writeFile(receiptPath, JSON.stringify(receipt, null, 2) + "\n");
  const descriptor = JSON.parse(await fs.readFile(versionDescriptor));
  receipt.package = descriptor;
  const archive = await fs.readFile(path.join(path.dirname(versionDescriptor), descriptor.filename));
  assert.equal("sha256:" + hash(archive), descriptor.sha256);
  await assert.rejects(fs.access(path.join(path.dirname(versionDescriptor), "manifest.json")), { code: "ENOENT" });
  receipt.asarSha256 = hash(await fs.readFile(path.join(res, "app.asar")));
  if (!windows) execFileSync("codesign", ["--verify", "--deep", "--strict", application]);
  receipt.signatureVerified = windows ? null : true;
  const env = { ...process.env, HOME: qaRoot, TMPDIR: qaRoot,
    CANDLESCOPE_RUNTIME_MODE: "LOCAL_OFFLINE", CANDLESCOPE_DESKTOP_USER_DATA: profile,
    CANDLESCOPE_DESKTOP_UI_PORT: "0", CANDLESCOPE_DESKTOP_BACKEND_PORT: "0",
    CANDLESCOPE_PLUGIN_PLATFORM_V2_ROOT: path.join(profile, "plugins"),
    CANDLESCOPE_LOCAL_DATA_DIR: path.join(profile, "library"), CANDLE_DATA_DIR: path.join(profile, "data"),
    BACKTEST_ENABLED: "1", BACKTEST_BAR_ENABLED: "1", REPLAY_ENABLED: "1",
  };
  for (const key of [
    "ELECTRON_RUN_AS_NODE", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV",
    "CANDLESCOPE_DESKTOP_URL", "CANDLESCOPE_DESKTOP_SKIP_SIDECAR",
    "CANDLESCOPE_DESKTOP_SIDECAR_COMMAND_JSON", "CANDLESCOPE_PYTHON",
  ]) delete env[key];
  const start = 1_700_000_040_000;
  const samples = [10, 10, 10, 20, 20, 5, 5, 15, 15, 8];
  const prices = Array.from({ length: 600 }, (_, i) => samples[i % samples.length]);
  const csv = ["time,open,high,low,close,volume",
    ...prices.map((v, i) => [start + i * 60_000, v, v + 1, v - 1, v, 100].join(",")),
  ].join("\n");
  receipt.dataset = { name: "Unified Pine 600", symbol: "BTCUSDT", interval: "1m",
    startMs: start, bars: prices.length, csvSha256: hash(csv) };
  const script = [
    "//@version=6", 'strategy("Unified threshold", initial_capital=10000)',
    "if close > 12", '    strategy.entry("L", strategy.long, qty=2)',
    "if close < 9", '    strategy.close("L")', "plot(close)",
  ].join("\n");
  receipt.strategySha256 = hash(script);
  let previousRun, savedReplay, savedPrefix, firstInstance;

  async function phase(name, fn) {
    const phase = { name };
    receipt.phases.push(phase);
    let app;
    try {
      app = await _electron.launch({ executablePath: executable, env, timeout: 120_000 });
      const identity = await app.evaluate(({ app }) => ({ pid: process.pid,
        packaged: app.isPackaged, profile: app.getPath("userData"), electron: process.versions.electron }));
      assert.equal(path.resolve(identity.profile), path.resolve(profile));
      assert.ok(identity.packaged);
      phase.electron = identity.electron;
      const window = await app.firstWindow({ timeout: 100_000 });
      await window.waitForURL(url => url.protocol === "http:" && url.hostname === "127.0.0.1", {
        waitUntil: "load", timeout: 90_000,
      });
      const bootstrap = await window.evaluate(() => window.candlescopeDesktop.getBootstrap());
      const command = bootstrap.sidecar.command.replace(/^\\\\\?\\/, "");
      const bundledPython = path.relative(path.join(res, "python-runtime"), command);
      assert.ok(bundledPython && !path.isAbsolute(bundledPython) && !bundledPython.startsWith(".."));
      const client = await window.evaluate(() => ({
        backend: new URL(window.candlescopeDesktop.apiBase).origin,
        management: window.candlescopeDesktop.getPluginManagementSession(),
        origin: location.origin,
      }));
      const invoke = async (url, opts = {}, expected = 200) => {
        const response = await fetch(client.backend + url, opts);
        const body = await response.json();
        assert.equal(response.status, expected, JSON.stringify(body).slice(0, 2500));
        return body;
      };
      const post = (url, body, additional = {}) => invoke(url, {
        method: "POST", headers: { "Content-Type": "application/json", ...additional },
        body: JSON.stringify(body),
      });
      const manage = (route, body, { action = false, expected = 200, binary = false } = {}) => {
        const headers = {
          Origin: client.origin, "X-CandleScope-Plugin-Session": client.management.sessionToken,
        };
        if (body !== undefined) {
          headers["Content-Type"] = binary ? "application/octet-stream" : "application/json";
          headers["X-CandleScope-CSRF"] = client.management.csrfToken;
        }
        if (action) headers["X-CandleScope-User-Action"] = "qa-" + randomUUID();
        return invoke("/api/v2/plugins/manage/unified" + route, {
          method: body === undefined ? "GET" : "POST", headers,
          body: body === undefined || binary ? body : JSON.stringify(body),
        }, expected);
      };
      const catalog = () => manage("");
      const getPine = data => {
        const pine = data.plugins.find(item => item.id === pineId);
        assert.ok(pine, JSON.stringify(data.errors));
        const entry = pine.entries[0];
        return { ...pine, entry, running: entry.observed.find(item => item.state === "running") };
      };
      const health = await invoke("/health");
      assert.equal(health.runtime_mode, "LOCAL_OFFLINE");
      assert.equal(health.local_offline.network.blocked_attempts, 0);
      const processTree = new Set([identity.pid]);
      const observeProcesses = () => {
        const all = children();
        for (let i = 0; i < 10; i++) {
          for (const [pid, ppid] of all) if (processTree.has(ppid)) processTree.add(pid);
        }
      };
      observeProcesses();
      const poll = async (inspect, done) => {
        for (let i = 0; i < 180; i++) {
          const value = await inspect();
          if (done(value)) return value;
          await pause(150);
        }
        throw new Error("Native run or replay did not settle");
      };
      const frame = async (pine, { horizon = 3, wrongDocument = false, overflow = false, stale = false } = {}) => {
        const documentId = "qa-window-" + randomUUID();
        const session = await manage("/realm", { clientId: documentId, realm: "frontend" });
        const boundary = start + horizon * 60_000 - 1;
        const bars = prices.slice(0, overflow ? horizon + 1 : horizon).map((v, index) => ({
          openTimeMs: start + index * 60_000, observedThroughMs: start + (index + 1) * 60_000 - 1,
          open: v, high: v + 1, low: v - 1, close: v, volume: 100, closed: true,
        }));
        return manage("/invoke-chart", {
          target: { sessionId: session.sessionId, pluginId: pineId, entryId: pine.entry.id,
            identity: pine.running.identity, instanceId: pine.running.instanceId },
          scope: { schema: "candlescope.unified-chart/1", documentId: wrongDocument ? "other" : documentId,
            chartId: "chart", instanceId: "visible-chart", mode: "replay", runId: "bars-run", trackId: "track",
            seriesId: "dataset", symbol: "BTCUSDT", interval: "1m", dataRevision: "qa-1", visibleThroughMs: boundary },
          bars, input: { source: '//@version=6\nindicator("QA")\nplot(close * 2)', parameters: {} },
        }, { expected: overflow || wrongDocument || stale ? 409 : 200 });
      };
      try {
        await fn({ phase, invoke, post, manage, catalog, getPine, frame, poll, observeProcesses });
        const finalHealth = await invoke("/health");
        phase.blockedNetworkAttempts = finalHealth.local_offline.network.blocked_attempts;
        assert.equal(phase.blockedNetworkAttempts, 0);
      } finally {
        observeProcesses();
        await app.close();
        app = undefined;
        for (let attempt = 0; attempt < 10; attempt++) {
          phase.remainingOwnedProcesses = children().filter(([pid]) => processTree.has(pid)).map(([pid]) => pid);
          if (!phase.remainingOwnedProcesses.length) break;
          await pause(250);
        }
        phase.ownedProcesses = processTree.size;
        assert.deepEqual(phase.remainingOwnedProcesses, []);
        const retained = await fs.readdir(path.join(profile, "plugins", "unified", "runs"));
        assert.deepEqual(retained, []);
        phase.retainedExecutionTrees = retained.length;
      }
    } catch (error) {
      phase.failure = String(error);
      throw error;
    } finally {
      if (app) await app.close();
      await save();
    }
  }

  await phase("seed-compute-run-save", async q => {
    const pine = q.getPine(await q.catalog());
    assert.equal(pine.desired.packageSha256, descriptor.sha256);
    assert.ok(pine.running);
    firstInstance = pine.running.instanceId;
    q.phase.instance = firstInstance;
    q.phase.pointValues = (await q.frame(pine, { horizon: 5 })).result.points.map(p => p.value);
    assert.deepEqual(q.phase.pointValues, [20, 20, 20, 40, 40]);
    for (const bad of [{ horizon: 3, overflow: true }, { wrongDocument: true }]) {
      const failure = await q.frame(pine, bad);
      assert.ok(failure.detail);
    }
    q.phase.rejectedFrames = ["beyond-visible-horizon", "different-document"];
    const dataset = await q.invoke("/api/v1/local/imports/csv?name=Unified+Pine+600&symbol=BTCUSDT&interval=1m&timestamp_unit=ms", {
      method: "POST", headers: { "Content-Type": "text/csv" }, body: csv,
    }, 201);
    const data = { dataset_id: dataset.dataset_id, data_epoch: dataset.data_epoch,
      start_time_ms: start, end_time_ms: start + prices.length * 60_000 - 1, interval: "1m" };
    const frozen = await q.post("/api/v1/backtests/datasets/snapshot", data);
    const body = { ...data, language: "pine", parameters: {},
      snapshot_hash: frozen.snapshot_hash, context: { symbol: "BINANCE:BTCUSDT", timeframe: "1" } };
    const invalidResponse = await q.post(originPath + "/runs", { ...body, source: "invalid()" }, { "Idempotency-Key": "invalid-pine" });
    const invalid = await q.poll(() => q.invoke(originPath + "/runs/" + invalidResponse.run_id),
      run => ["FAILED", "COMPLETED"].includes(run.state));
    assert.equal(invalid.state, "FAILED");
    q.phase.invalidInput = invalid.error?.code ?? invalid.state;
    const created = await q.post(originPath + "/runs", { ...body, source: script }, { "Idempotency-Key": "valid-pine" });
    previousRun = await q.poll(() => q.invoke(originPath + "/runs/" + created.run_id),
      run => ["FAILED", "COMPLETED"].includes(run.state));
    assert.equal(previousRun.state, "COMPLETED", JSON.stringify(previousRun.error));
    assert.equal(previousRun.runtime_launch.installation.packageSha256, descriptor.sha256);
    assert.ok(previousRun.result.orders.length && previousRun.result.trades.length && previousRun.result.graphics.length);
    assert.equal(previousRun.result.equity.length, prices.length);
    q.phase.run = { id: created.run_id, orders: previousRun.result.orders.length,
      trades: previousRun.result.trades.length, equity: previousRun.result.equity.length,
      graphics: previousRun.result.graphics.length, engine: previousRun.result.identity };
    const replay = await q.post(originPath + "/replays", { run_id: created.run_id });
    const replayBase = originPath + "/replays/" + replay.replay_id;
    await q.post(replayBase + "/commands", { action: "seek", target: 60, revision: replay.revision });
    const advanced = await q.poll(() => q.invoke(replayBase), value => value.cursor === 60 || value.state === "FAILED");
    assert.equal(advanced.cursor, 60, JSON.stringify(advanced.error));
    assert.equal(advanced.result.bars.length, 60);
    savedPrefix = advanced.result;
    savedReplay = await q.post(replayBase + "/commands", { action: "snapshot", revision: advanced.revision });
    q.phase.replay = { id: replay.replay_id, cursor: savedReplay.cursor,
      snapshot: savedReplay.snapshots[0].snapshot_id, method: savedReplay.method };
    q.observeProcesses();
  });

  await phase("restart-restore-complete-disable", async q => {
    const pine = q.getPine(await q.catalog());
    assert.equal(pine.desired.packageSha256, descriptor.sha256);
    assert.notEqual(pine.running.instanceId, firstInstance);
    q.phase.instance = pine.running.instanceId;
    const loaded = await q.invoke(originPath + "/runs/" + previousRun.run_id);
    assert.deepEqual(loaded.result, previousRun.result);
    const base = originPath + "/replays/" + savedReplay.replay_id;
    const replay = await q.invoke(base);
    const restored = await q.post(base + "/commands", { action: "restore", revision: replay.revision,
      snapshot_id: savedReplay.snapshots[0].snapshot_id });
    assert.deepEqual(restored.result, savedPrefix);
    await q.post(base + "/commands", { action: "seek", revision: restored.revision, target: prices.length });
    const result = await q.poll(() => q.invoke(base), value => value.state === "COMPLETED" || value.state === "FAILED");
    assert.equal(result.state, "COMPLETED", JSON.stringify(result.error));
    assert.deepEqual(result.result, previousRun.result);
    q.phase.restoredBars = restored.cursor;
    q.phase.completedBars = result.cursor;
    q.phase.ledgerMatchesBatch = true;
    q.observeProcesses();
    if (candidateUpgrade) {
      const review = await q.manage("/stage", await fs.readFile(candidateUpgrade), { action: true, binary: true });
      const changed = await q.manage("/change", {
        action: "activate", digest: review.packageSha256, revision: (await q.catalog()).revision,
        acknowledgement: "full-trust:" + review.packageSha256,
      }, { action: true });
      const upgraded = q.getPine(changed.catalog);
      assert.notEqual(upgraded.desired.packageSha256, descriptor.sha256);
      assert.notEqual(upgraded.running.instanceId, pine.running.instanceId);
      assert.deepEqual((await q.frame(upgraded, { horizon: 3 })).result.points.map(p => p.value), [20, 20, 20]);
      await q.frame(pine, { stale: true });
      q.phase.updatedTo = upgraded.running.identity;
      const rollback = await q.manage("/change", {
        action: "activate", digest: descriptor.sha256, revision: (await q.catalog()).revision,
        acknowledgement: "full-trust:" + descriptor.sha256,
      }, { action: true });
      const rolledBack = q.getPine(rollback.catalog);
      assert.equal(rolledBack.running.identity.packageSha256, descriptor.sha256);
      assert.ok(rolledBack.running.identity.generation > upgraded.running.identity.generation);
      await q.frame(upgraded, { stale: true });
      assert.deepEqual((await q.frame(rolledBack, { horizon: 3 })).result.points.map(p => p.value), [20, 20, 20]);
      q.phase.rolledBackTo = rolledBack.running.identity;
    }
    const catalog = await q.catalog();
    const disabled = await q.manage("/change", { action: "disable", id: pineId, revision: catalog.revision }, { action: true });
    const off = q.getPine(disabled.catalog);
    assert.equal(off.desired.enabled, false);
    assert.equal(off.running, undefined);
    await q.frame(pine, { stale: true });
    q.phase.disabled = true;
  });

  await phase("restart-disabled", async q => {
    const pine = q.getPine(await q.catalog());
    assert.equal(pine.desired.enabled, false);
    assert.equal(pine.running, undefined);
    assert.deepEqual((await q.invoke(originPath + "/runs/" + previousRun.run_id)).result, previousRun.result);
    q.phase.savedRunPreserved = true;
  });
  receipt.ok = true;
  await save();
})().catch(error => { console.error(error); process.exitCode = 1; });
