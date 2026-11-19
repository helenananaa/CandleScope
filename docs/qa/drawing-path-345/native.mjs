import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import { ControlClient } from "../../../packages/candlescope-control/client.mjs";
import * as q from "../replay-imported-bar-20261104/native-driver.mjs";

assert.ok(process.env.CANDLESCOPE_BATCH1_QA_ROOT);
await fs.mkdir(q.s.root + "/profile");
q.s.env = { ...q.s.env, CANDLESCOPE_RUNTIME_MODE: "LIVE", PYTHONDONTWRITEBYTECODE: "1" };
q.s.receipt.schema = "candlescope.drawing-path-native/1";
q.s.receipt.transport = "Packaged renderer, real chart pointer and keyboard, isolated LIVE profile with seeded minute bars";
const resources = await fs.realpath(q.s.root + "/Installed App/CandleScope.app/Contents/Resources");
execFileSync(resources + "/python-runtime/python/bin/python3", ["-B", "docs/qa/practice-hedge-343/seed_market.py"], {
  env: { ...q.s.env, CANDLESCOPE_BATCH1_QA_ROOT: q.s.root, CANDLE_DATA_DIR: q.s.root + "/profile/data",
    KLINES_DB_PATH: q.s.root + "/profile/data/candlescope.db", PYTHONPATH: resources + "/backend:" + resources + "/python-runtime/site-packages" },
});

async function launch() {
  await q.launch();
  const page = q.s.page;
  await page.getByRole("button", { name: "设置", exact: true }).click({ timeout: 90000 });
  await page.getByRole("button", { name: "AI MCP", exact: true }).click();
  await page.getByRole("checkbox", { name: /为本次授权启用可选/ }).check();
  await page.getByRole("checkbox", { name: /允许本机客户端/ }).check();
  await page.getByRole("button", { name: "启用控制", exact: true }).click();
  await page.getByRole("button", { name: "关闭设置", exact: true }).click();
  q.s.control = new ControlClient(q.s.root + "/profile/control/connection.json");
  await q.s.control.connect();
}

async function pane(id = "cell-1") {
  const { snapshot } = await q.s.control.call("app.query", { windowId: "main-window", groupId: "drawings:" + id, command: "inspect", args: {} });
  return snapshot.panes.find(p => p.paneId === "main");
}
async function command(command, args, groupId = "drawings:cell-1") {
  const { groups } = await q.s.control.call("app.commands", { windowId: "main-window" });
  const group = groups.find(g => g.id === groupId);
  const requestId = "native345-" + crypto.randomUUID();
  await q.s.control.call("app.execute", { windowId: "main-window", groupId: group.id, command, args, requestId, expectedContext: group.contextToken });
  const result = await q.until(async () => { const r = await q.s.control.call("request.get", { requestId }); return r.final && r; });
  assert.equal(result.state, "applied", JSON.stringify(result));
}
async function select(tool) {
  const lineGroup = q.s.page.locator(".drawing-tool-btn").filter({ visible: true });
  const selector = '[data-drawing-tool^="line-"],[data-drawing-tool^="path-"]';
  await lineGroup.and(q.s.page.locator(selector)).first().click({ button: "right" });
  await q.s.page.locator('[data-tool-variant="' + tool + '"]').click();
}
function payload(p) {
  return p.zOrder.map(id => {
    const { kind, geometry, style } = p.entities.find(e => e.id === id);
    return { id, kind, geometry, style };
  });
}
async function changeInterval(interval) {
  assert.equal((await q.execute("cell-1", "interval", { interval })).state, "applied");
  await q.until(async () => {
    const snap = await q.inspect();
    return snap.cells[0].runtime.marketReady && !snap.cells[0].runtime.loading && snap.persistence.state === "saved" && (await pane()).ready;
  }, 90000);
}
async function reopenAt15m() {
  await exit();
  await launch();
  await q.until(async () => {
    const snap = await q.inspect();
    return snap.cells[0].session.interval === "15m" && snap.persistence.state === "saved" && (await pane()).ready;
  }, 90000);
}
async function exit() {
  await q.quit();
  assert.equal(await q.exited(), true);
}
try {
  await launch();
  const chartSpec = { session: { exchange: "binance", marketType: "futures", symbol: "BTCUSDT", interval: "1m" }, indicators: [] };
  const layout = await q.configure([chartSpec, chartSpec], "split-vertical");
  assert.ok(["ready", "applied"].includes(layout.result.state));
  await q.ready(2, 90000);
  await command("preferences", { snap: false, continuous: false });
  const chart = q.s.page.locator('[data-chart-cell-id="cell-1"] .chart-pane').first();
  const box = await chart.boundingBox();
  assert.ok(box);
  const pos = (x, y) => ({ x: Math.round(box.width * x), y: Math.round(box.height * y) });
  await chart.hover();
  await select("path-arrow");
  await chart.click({ position: pos(.62, .72) });
  await chart.click({ position: pos(.62, .38) });
  await chart.click({ position: pos(.28, .65) });
  await chart.dblclick({ position: pos(.37, .50) });
  const arrow = await q.until(async () => (await pane()).entities.find(e => e.kind === "path"));
  const points = arrow.geometry.dataPoints;
  assert.equal(points.length, 4);
  assert.equal(arrow.style.arrowEnd, true);
  assert.equal(points[0].time, points[1].time);
  assert.notEqual(points[0].price, points[1].price);
  assert.ok(points[2].time < points[1].time);
  await select("path-arrow");
  const vertex = pos(.62, .38), destination = pos(.67, .33);
  await q.s.page.mouse.move(box.x + vertex.x, box.y + vertex.y);
  await q.s.page.mouse.down();
  await q.s.page.mouse.move(box.x + destination.x, box.y + destination.y, { steps: 5 });
  await q.s.page.mouse.up();
  const edited = await q.until(async () => {
    const current = (await pane()).entities.find(e => e.id === arrow.id);
    return current && current.geometry.dataPoints[1].price !== points[1].price && current;
  });
  assert.deepEqual(edited.geometry.dataPoints.filter((_, i) => i !== 1), points.filter((_, i) => i !== 1));
  const middle = pos((.62 + .67) / 2, (.72 + .33) / 2);
  await chart.click({ position: middle, button: "right" });
  await q.s.page.getByRole("menuitem", { name: "插入顶点", exact: true }).click();
  await q.until(async () => (await pane()).entities[0].geometry.dataPoints.length === 5);
  await command("undo", { paneId: "main" });
  assert.deepEqual((await pane()).entities[0].geometry, edited.geometry);
  await q.record("vertex-drag-insert-undo", { original: points, edited: edited.geometry.dataPoints });
  await command("updatePriceScale", { cellId: "cell-1", invertScale: false, priceScaleMode: 1 }, "workspace");
  await q.s.page.mouse.move(box.x + middle.x, box.y + middle.y);
  await q.s.page.mouse.wheel(0, -90);
  await q.delay(350);
  assert.deepEqual((await pane()).entities[0].geometry, edited.geometry);
  await q.screenshot("log-zoom");
  await select("path-line");
  await chart.click({ position: pos(.32, .23) });
  await chart.click({ position: pos(.50, .29) });
  await q.s.page.keyboard.press("Enter");
  await q.until(async () => (await pane()).entities.length === 2);
  const expected = payload(await pane());
  assert.equal(expected[1].geometry.dataPoints.length, 2);
  assert.ok(!expected[1].style.arrowEnd);
  await command("undo", { paneId: "main" });
  assert.deepEqual(payload(await pane()), expected.slice(0, 1));
  await command("redo", { paneId: "main" });
  assert.deepEqual(payload(await pane()), expected);
  assert.deepEqual(payload(await pane("cell-2")), []);
  await q.record("two-independent-charts", { expected, other: payload(await pane("cell-2")) });
  await q.screenshot("one-minute");
  await changeInterval("15m");
  assert.deepEqual(payload(await pane()), expected);
  await q.screenshot("fifteen-minute");
  await q.record("saved-at-15m", { drawings: payload(await pane()) });
  await reopenAt15m();
  assert.deepEqual(payload(await pane()), expected);
  await changeInterval("1m");
  await q.ready(2, 90000);
  await q.until(async () => (await pane()).ready);
  assert.deepEqual(payload(await pane()), expected);
  assert.deepEqual(payload(await pane("cell-2")), []);
  await q.screenshot("restored");
  await q.record("restored-after-full-exit", { restored: payload(await pane()), packaged: q.s.identity.packaged });
  await command("createLinkGroup", { cellIds: ["cell-1", "cell-2"] }, "workspace");
  const { cells } = await q.inspect();
  const groupId = cells[0].linkGroupId;
  assert.ok(groupId && cells[1].linkGroupId === groupId);
  await command("updateLinkPolicy", { groupId, relationship: "peers", patch: { drawings: true } }, "workspace");
  await q.until(async () => {
    const a = await pane(), b = await pane("cell-2");
    return a?.ready && b?.ready && a.scopeKey === b.scopeKey;
  });
  const beforeLink = payload(await pane());
  const linkedChart = q.s.page.locator('[data-chart-cell-id="cell-1"] .chart-pane').first();
  await linkedChart.hover();
  await select("path-arrow");
  await linkedChart.click({ position: pos(.18, .75) });
  await linkedChart.click({ position: pos(.43, .35) });
  await linkedChart.dblclick({ position: pos(.66, .58) });
  await q.until(async () => (await pane("cell-2")).entities.length === beforeLink.length + 1);
  const linked = payload(await pane());
  assert.deepEqual(payload(await pane("cell-2")), linked);
  const p = await pane();
  await command("apply", { paneId: "main", scopeKey: p.scopeKey, expectedRevision: p.revision,
    commands: [{ type: "delete", id: linked.at(-1).id }] });
  await q.until(async () => (await pane("cell-2")).entities.length === beforeLink.length);
  await command("undo", { paneId: "main" });
  await q.until(async () => (await pane("cell-2")).entities.length === linked.length);
  assert.deepEqual(payload(await pane("cell-2")), linked);
  await q.record("linked-create-delete-undo", { groupId, first: linked, second: payload(await pane("cell-2")) });
  await changeInterval("15m");
  assert.deepEqual(payload(await pane()), linked);
  await reopenAt15m();
  await q.until(async () => (await pane("cell-2")).ready);
  assert.deepEqual(payload(await pane()), linked);
  assert.deepEqual(payload(await pane("cell-2")), linked);
  await changeInterval("1m");
  await q.until(async () => (await pane("cell-2")).ready);
  assert.deepEqual(payload(await pane()), linked);
  assert.deepEqual(payload(await pane("cell-2")), linked);
  await q.screenshot("linked-restored");
  await q.record("linked-restart-interval-round-trip", { first: payload(await pane()), second: payload(await pane("cell-2")) });
  await exit();
  assert.deepEqual(q.s.receipt.errors, []);
  q.s.receipt.passed = true;
  await q.save();
} catch (error) {
  q.s.receipt.passed = false;
  q.s.receipt.failure = String(error.stack ?? error);
  await q.save();
  console.error(error);
  try { await q.screenshot("failure"); await fs.writeFile(q.s.root + "/failure.txt", await q.s.page.locator("body").ariaSnapshot()); } catch {}
  try { await exit(); } catch {}
  process.exitCode = 1;
}
