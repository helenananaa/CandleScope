import assert from "node:assert/strict";
import fs from "node:fs/promises";
import cp from "node:child_process";
import path from "node:path";
import { pathToFileURL } from "node:url";

const driver = "docs/qa/indicator-domain-native-20261106";
const q = await import(pathToFileURL(path.resolve(driver, "native-driver.mjs")));
const id = "native-pine-rollout";
const script = '//@version=6\nindicator("Native Pine rollout")\nlength = input.int(7, "Length")\nplot(ta.sma(close, length), "SMA")';
const inputKey = "1";
const params = { [inputKey]: 9 };
const root = q.s.root;
await q.assertPublicGate();
await assert.rejects(fs.stat(path.join(root, "profile")), { code: "ENOENT" });
await fs.mkdir(path.join(root, "home"), { recursive: true });
Object.assign(q.s.env, { HOME: path.join(root, "home"), CANDLESCOPE_RUNTIME_MODE: "LIVE", PYTHONDONTWRITEBYTECODE: "1" });
q.s.receipt.scope = "Same signed macOS arm64 candidate and isolated profile, calculation to snapshot and back, public Binance spot 1m.";
const original = {};
let running = false;

function verifyPackage() {
  cp.execFileSync("node", [path.join(driver, "verify.mjs")], {
    stdio: "inherit",
    env: { ...process.env, CANDLESCOPE_BATCH1_QA_ROOT: root },
  });
}
async function json(url, body) {
  const response = await fetch(q.s.backend + url, body === undefined ? undefined : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  assert.equal(response.status, 200);
  return response.json();
}
async function launch(mode, explicit) {
  if (explicit) q.s.env.CANDLESCOPE_PINE_CHART_TRANSPORT = mode;
  else delete q.s.env.CANDLESCOPE_PINE_CHART_TRANSPORT;
  const start = { requests: q.s.traffic.requests.length, sockets: q.s.traffic.sockets.length };
  q.s.app = null;
  running = true;
  const launch = await q.launch();
  const renderer = await q.s.page.evaluate(() => window.candlescopeDesktop.pineChartTransport);
  const backend = (await json("/health")).pine_chart_transport;
  assert.equal(renderer, mode);
  assert.equal(backend, mode);
  await q.record("launch-transport", { mode, renderer, backend, launch });
  await q.s.page.getByRole("button", { name: "设置", exact: true }).waitFor({ timeout: 60000 });
  await q.enableControl();
  return start;
}
async function qualify(mode, start) {
  const accepted = await q.until(async () => {
    await q.checkCircuit();
    const workspace = await q.inspect();
    const cell = workspace.cells[0];
    if (!cell || workspace.persistence.state !== "saved" || !cell.runtime.marketReady ||
        cell.runtime.loading || !cell.runtime.indicatorsReady || cell.runtime.computing ||
        cell.runtime.indicatorErrors?.length || !cell.runtime.indicatorOutputPoints?.some(count => count > 0)) return false;
    const requests = q.s.traffic.requests.slice(start.requests).filter(r => r.url.includes("/indicators/"));
    for (const socket of q.s.traffic.sockets.slice(start.sockets)) {
      if (!socket.url.includes("/stream/indicators")) continue;
      for (const raw of socket.sent) {
        if (!raw.startsWith("{")) continue;
        const message = JSON.parse(raw);
        if (message.action !== "subscribe" || message.script !== script) continue;
        const events = (socket.events ?? []).filter(event => event.clientId === message.clientId);
        const ack = events.find(event => event.type === "indicator.subscribed" && event.ok === true);
        const output = events.find(event => ["indicator.snapshot", "indicator.replace_range", "indicator.patch"].includes(event.type)
          && event.points > 0 && event.ok !== false);
        if (ack && output) return { workspace, requests, message, ack, output };
      }
    }
    return false;
  }, 180000);
  const definition = (await q.query("cell-1")).snapshot.indicators.find(row => row.id === id);
  assert.equal(definition?.script, script);
  assert.equal(definition?.params?.[inputKey], params[inputKey]);
  const { requests, message, output } = accepted;
  if (mode === "calculation") {
    assert.ok(requests.some(r => r.method === "POST" && r.url.endsWith("/indicators/calculations")));
    assert.ok(message.calculation?.domainId);
    assert.equal(message.pineChartTransport, undefined);
    assert.equal(output.calculation?.domainId, message.calculation.domainId);
  } else {
    assert.ok(requests.some(r => r.method === "POST" && /\/indicators\/range(?:\/batch)?$/.test(r.url)));
    assert.equal(requests.some(r => r.method === "POST" && r.url.includes("/indicators/calculations")), false);
    assert.equal(message.pineChartTransport, "snapshot");
    assert.equal(message.calculation, undefined);
    assert.equal(output.calculation, undefined);
  }
  await q.record("saved-rendered-transport", { mode, ...accepted, definition });
  await q.screenshot("pine-transport-" + mode + "-" + start.sockets);
  return accepted;
}
async function close() {
  await q.quit();
  assert.equal(await q.exited(), true);
  running = false;
  const status = JSON.parse(await fs.readFile(path.join(root, "sidecar-exit-status.json")));
  const pid = q.s.bootstrap.sidecar.pid;
  const exit = status.exits.find(item => item.pid === pid);
  assert.equal(exit?.code, 0);
  assert.equal(exit?.signal, null);
  assert.ok(!status.killRequests.some(item => item.pid === pid));
  verifyPackage();
  await q.record("normal-full-exit", { exit, owned: q.s.quitPids, strictSignature: true });
}
async function checkStale(expected) {
  const payload = await json("/api/v1/indicators/calculations/" + original.ref.domainId + "/range", {
    clientId: id, calculation: original.ref, start: original.start, end: original.end,
  });
  assert.equal(payload.code, expected, JSON.stringify(payload));
  await q.record("stale-reference-refused", { expected, code: payload.code, domainId: original.ref.domainId });
}

try {
  verifyPackage();
  await fs.copyFile(path.join(root, "verified-after.json"), path.join(root, "verified-before.json"));
  let start = await launch("calculation", false);
  const configured = await q.configure([{ session: q.session("BTCUSDT", "1m"), indicators: [] }], "single");
  assert.ok(["applied", "ready"].includes(configured.result.state), JSON.stringify(configured.result));
  const added = await q.execute("cell-1", "addIndicator", {
    id, name: "Native Pine rollout", kind: "script", executionTarget: "hosted",
    language: "pine", securityMode: "safe", script, params, visible: true,
  });
  assert.equal(added.state, "applied", JSON.stringify(added));
  const initial = await qualify("calculation", start);
  original.ref = initial.message.calculation;
  original.start = initial.output.range.start;
  original.end = initial.output.range.end;
  await close();

  start = await launch("snapshot", true);
  await checkStale("INDICATOR_PINE_CHART_TRANSPORT_MISMATCH");
  await qualify("snapshot", start);
  await close();

  start = await launch("calculation", true);
  await checkStale("INDICATOR_CALCULATION_NOT_FOUND");
  const restored = await qualify("calculation", start);
  assert.notEqual(restored.message.calculation.domainId, original.ref.domainId);
  assert.deepEqual(q.s.receipt.errors, []);
  await close();
  q.s.receipt.passed = true;
} catch (error) {
  q.s.receipt.passed = false;
  q.s.receipt.failure = String(error.stack ?? error);
  process.exitCode = 1;
  if (q.s.page) await q.screenshot("failure").catch(() => {});
} finally {
  if (running && q.s.app) {
    try { await close(); } catch (error) { q.s.receipt.exitFailure = String(error.stack ?? error); }
  }
  await q.save();
  console.log(JSON.stringify({ passed: q.s.receipt.passed, failure: q.s.receipt.failure }));
}
