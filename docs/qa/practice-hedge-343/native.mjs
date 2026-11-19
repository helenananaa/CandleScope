import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { execFileSync } from "node:child_process";
import { ControlClient } from "../../../packages/candlescope-control/client.mjs";
import * as q from "../replay-imported-bar-20261104/native-driver.mjs";

assert.ok(process.env.CANDLESCOPE_BATCH1_QA_ROOT);
await fs.mkdir(q.s.root + "/profile");
q.s.env = { ...q.s.env, CANDLESCOPE_RUNTIME_MODE: "LIVE", PYTHONDONTWRITEBYTECODE: "1" };
q.s.receipt.schema = "candlescope.practice-hedge-native/1";
q.s.receipt.scope = "macOS installed LIVE app, isolated local practice ledger, BTC and ETH futures";
q.s.receipt.transport = "Packaged UI and HTTP API, two controlled 1m series seeded in an isolated market database";
const resources = await fs.realpath(q.s.root + "/Installed App/CandleScope.app/Contents/Resources");
execFileSync(resources + "/python-runtime/python/bin/python3", ["-B", "docs/qa/practice-hedge-343/seed_market.py"], {
  env: { ...q.s.env, CANDLESCOPE_BATCH1_QA_ROOT: q.s.root, CANDLE_DATA_DIR: q.s.root + "/profile/data",
    KLINES_DB_PATH: q.s.root + "/profile/data/candlescope.db", PYTHONPATH: [resources + "/backend",
      resources + "/python-runtime/site-packages"].join(":") },
});
const panel = () => q.s.page.locator(".trading-panel");
async function api(path, body) {
  const result = await fetch(q.s.backend + "/api/v1/trading/accounts" + path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const text = await result.text();
  assert.ok(result.ok, path + " " + text);
  return JSON.parse(text);
}
async function observeAccount(path, accept = () => true, afterConnect) {
  const controller = new AbortController();
  const response = await fetch(q.s.backend + "/api/v1/trading/accounts" + path + "/events", { signal: controller.signal });
  assert.ok(response.ok);
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  const deadline = setTimeout(() => controller.abort(), 30000);
  try {
    let initial = true;
    while (true) {
      const newline = buffer.indexOf("\n");
      if (newline < 0) {
        const part = await reader.read();
        assert.equal(part.done, false);
        buffer += part.value;
        continue;
      }
      const frame = JSON.parse(buffer.slice(0, newline));
      buffer = buffer.slice(newline + 1);
      if (frame.type === "heartbeat") continue;
      assert.equal(frame.type, "snapshot");
      if (initial && afterConnect) {
        initial = false;
        await afterConnect(frame);
      } else if (accept(frame)) return frame;
    }
  } finally {
    clearTimeout(deadline);
    controller.abort();
    await reader.cancel().catch(() => {});
  }
}
async function launch() {
  await q.launch();
  q.s.page.setDefaultTimeout(20000);
  await q.s.page.getByRole("navigation").first().waitFor({ timeout: 90000 });
  await q.record("launch", { pid: q.s.identity.pid, packaged: q.s.identity.packaged });
  if (!await panel().isVisible()) await q.s.page.getByRole("button", { name: "交易账户", exact: true }).click();
}
async function enableChartControls() {
  await q.s.page.getByRole("button", { name: "设置", exact: true }).click();
  await q.s.page.getByRole("button", { name: "AI MCP", exact: true }).click();
  await q.s.page.getByRole("checkbox", { name: /为本次授权启用可选/ }).check();
  await q.s.page.getByRole("checkbox", { name: /允许本机客户端/ }).check();
  await q.s.page.getByRole("button", { name: "启用控制", exact: true }).click();
  await q.s.page.getByRole("button", { name: "关闭设置", exact: true }).click();
  q.s.control = new ControlClient(q.s.root + "/profile/control/connection.json");
  await q.s.control.connect();
}
async function switchChart(symbol) {
  const change = await q.configure([{ session: { exchange: "binance", marketType: "futures", symbol, interval: "1m" },
    indicators: [] }], "single");
  assert.ok(["ready", "applied"].includes(change.result.state));
}
async function ticket(label, qty, stop, target) {
  const form = panel().locator(".trading-ticket");
  await form.getByRole("radio", { name: label, exact: true }).click();
  await form.getByLabel(/^数量/).fill(qty);
  if (stop) await form.getByLabel("止损价").fill(stop);
  if (target) await form.getByLabel("止盈价").fill(target);
  const response = q.s.page.waitForResponse(r => r.url().endsWith("/orders") && r.request().method() === "POST");
  await form.getByRole("button", { name: label, exact: true }).click();
  const saved = await response;
  assert.equal(saved.status(), 200, await saved.text());
  const result = await saved.json();
  assert.equal(result.order.status, "filled");
  return result;
}
async function exit() {
  await q.quit();
  assert.equal(await q.exited(), true);
}
try {
  await launch();
  await panel().getByRole("button", { name: "添加账户", exact: true }).first().click();
  const dialog = q.s.page.getByRole("dialog", { name: "添加账户" });
  await dialog.getByLabel("名称", { exact: true }).fill("Hedge 343");
  await dialog.getByRole("radio", { name: "多空双向持仓" }).click();
  await dialog.getByLabel("初始资金（USDT）", { exact: true }).fill("1000000");
  const creation = q.s.page.waitForResponse(r => r.url().endsWith("/trading/accounts") && r.request().method() === "POST");
  await dialog.getByRole("button", { name: "创建", exact: true }).click();
  const account = await (await creation).json();
  assert.equal(account.settings.positionMode, "HEDGE");
  const path = "/" + account.id;
  const summary = () => api(path + "/summary");
  const order = async (symbol, positionSide, positionEffect, qty, extra = {}) => {
    const result = await api(path + "/orders", { exchange: "binance", marketType: "futures", symbol,
      positionSide, positionEffect, type: "market", qty, referencePrice: symbol === "BTCUSDT" ? "100000" : "3000", ...extra });
    assert.equal(result.order.positionSide, positionSide);
    assert.equal(result.order.positionEffect, positionEffect);
    assert.equal(result.order.status, "filled");
    return result;
  };
  await enableChartControls();
  await switchChart("BTCUSDT");
  const long = await ticket("开多", "0.002", "1", "9000000");
  const short = await ticket("开空", "0.001", "9000000", "1");
  assert.equal(long.order.positionSide, "LONG");
  assert.equal(short.order.positionSide, "SHORT");
  const eth = await order("ETHUSDT", "LONG", "open", "0.01");
  const both = await summary();
  assert.equal(both.positions.length, 3);
  assert.equal(both.workingOrders.length, 4);
  await q.record("held", { entries: [long, short, eth].map(r => [r.order.positionSide, r.referencePrice, r.priceSource]), positions: both.positions, usedMargin: both.usedMargin });
  const longTrade = both.positions.find(t => t.symbol === "BTCUSDT" && t.positionSide === "LONG");
  const shortTrade = both.positions.find(t => t.symbol === "BTCUSDT" && t.positionSide === "SHORT");
  const note = await api(path + "/journal", { exchange: "binance", marketType: "futures", symbol: "BTCUSDT", kind: "note",
    tradeId: shortTrade.id, fields: { entryBasis: "343 short only" } });
  assert.equal(note.positionSide, "SHORT");
  await switchChart("ETHUSDT");
  const positions = panel().getByRole("tab", { name: /^持仓/ });
  await positions.click();
  const longRow = panel().locator("article").filter({ hasText: "BTCUSDT" }).filter({ hasText: "0.002" }).filter({
    has: q.s.page.getByRole("button", { name: "市价平仓", exact: true }),
  });
  await longRow.getByRole("button", { name: "市价平仓", exact: true }).click();
  await q.until(async () => (await summary()).positions.length === 2);
  const settled = await summary();
  assert.deepEqual(settled.workingOrders.map(o => o.positionSide), ["SHORT", "SHORT"]);
  assert.ok(settled.positions.some(t => t.id === shortTrade.id));
  assert.equal((await api(path + "/trades/" + longTrade.id)).status, "closed");
  const associated = await api(path + "/trades/" + shortTrade.id);
  assert.deepEqual(associated.entries.map(e => e.id), [note.id]);
  assert.deepEqual((await api(path + "/trades/" + longTrade.id)).entries, []);
  const firstFrame = await observeAccount(path);
  assert.deepEqual(firstFrame.state.summary.positions.map(t => t.id), settled.positions.map(t => t.id));
  const fills = (await api(path + "/fills")).fills;
  assert.equal(fills.length, 4);
  await q.screenshot("btc-eth-hedge");
  await q.record("saved", { account: account.id, balance: settled.balance, fills, short: shortTrade.id, note: note.id });
  await exit();
  await launch();
  await panel().getByRole("combobox", { name: "当前账户" }).selectOption(account.id);
  await panel().getByRole("tab", { name: /^持仓/ }).click();
  await panel().getByText("ETHUSDT", { exact: true }).first().waitFor();
  const restored = await summary();
  assert.deepEqual(restored.positions.map(t => [t.id,t.positionSide,t.openQty]), settled.positions.map(t => [t.id,t.positionSide,t.openQty]));
  assert.deepEqual(restored.workingOrders, settled.workingOrders);
  assert.equal(restored.balance, settled.balance);
  assert.deepEqual((await api(path + "/fills")).fills, fills);
  assert.ok(JSON.stringify(await api(path + "/trades/" + shortTrade.id)).includes("343 short only"));
  const reconnected = await observeAccount(path);
  assert.equal(reconnected.identity.ledgerEpoch, firstFrame.identity.ledgerEpoch);
  assert.notEqual(reconnected.connectionEpoch, firstFrame.connectionEpoch);
  const flatOrdersFrame = await observeAccount(path, frame => !frame.state.summary.workingOrders.length, async initial => {
    assert.equal(initial.state.summary.workingOrders.length, 2);
    for (const working of restored.workingOrders) await api(path + "/orders/" + working.id + "/cancel", {});
  });
  assert.equal(flatOrdersFrame.state.summary.positions.length, 2);
  assert.ok(flatOrdersFrame.state.cursor.sequence > reconnected.state.cursor.sequence);
  const unprotected = await summary();
  assert.equal(unprotected.workingOrders.length, 0);
  assert.deepEqual(unprotected.feeds.map(f => f.symbol).sort(), ["BTCUSDT", "ETHUSDT"]);
  assert.equal(unprotected.positions.length, 2);
  const beforeMarks = Object.fromEntries(unprotected.feeds.map(feed => [feed.symbol, feed.observedMs]));
  const updated = await q.until(async () => {
    const current = await summary();
    return current.feeds.length === 2 && current.feeds.every(feed =>
      feed.status === "live" && feed.observedMs > beforeMarks[feed.symbol]) ? current : false;
  }, 90000);
  assert.equal(updated.workingOrders.length, 0);
  assert.deepEqual(updated.positions.map(t => t.id), unprotected.positions.map(t => t.id));
  for (const position of updated.positions) {
    const feed = updated.feeds.find(item => item.symbol === position.symbol);
    assert.equal(position.markPrice, feed.lastPrice);
  }
  await q.record("both-markets-held-without-orders", { beforeMarks, positions: updated.positions, feeds: updated.feeds,
    reconnectedLedger: reconnected.identity.ledgerEpoch });
  await enableChartControls();
  await switchChart("BTCUSDT");
  await panel().getByRole("tab", { name: "下单", exact: true }).click();
  const closed = await ticket("平空", "0.003");
  assert.equal(closed.order.filledQty, "0.001");
  const final = await summary();
  assert.equal(final.positions.length, 1);
  assert.equal(final.positions[0].symbol, "ETHUSDT");
  assert.equal(final.workingOrders.length, 0);
  await q.record("restored-and-closed-short", { position: final.positions[0].id, fillsBefore: fills.length, balance: final.balance });
  assert.deepEqual(q.s.receipt.errors, []);
  await exit();
  q.s.receipt.passed = true;
} catch (error) {
  q.s.receipt.failure = String(error.stack);
  console.error(error);
  try { await fs.writeFile(q.s.root + "/failure.txt", await q.s.page.locator("body").ariaSnapshot({ timeout: 3000 })); } catch {}
  if (q.s.app) await q.s.app.close().catch(() => {});
  process.exitCode = 1;
} finally { await q.save(); }
