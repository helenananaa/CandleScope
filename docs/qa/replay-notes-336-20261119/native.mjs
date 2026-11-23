import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { gunzipSync } from "node:zlib";
import { createHash } from "node:crypto";
import * as q from "../replay-imported-bar-20261104/native-driver.mjs";
const start = 1700000040000;
assert.ok(process.env.CANDLESCOPE_BATCH1_QA_ROOT, "Use a fresh acceptance directory");
const root = q.s.root;
q.s.receipt.scope = "macOS arm64 packaged Replay notes, two runs and two imported BAR markets per run";
await fs.mkdir(root + "/profile");
q.s.env = {
  ...q.s.env,
  CANDLESCOPE_RUNTIME_MODE: "LOCAL_OFFLINE",
  REPLAY_ENABLED: "1",
  KLINES_DB_PATH: root + "/profile/data/market.db",
  REPLAY_DB_PATH: root + "/profile/data/replay.db",
  BACKTEST_DB_PATH: root + "/profile/data/backtest.db",
  BACKTEST_ENABLED: "1",
  BACKTEST_BAR_ENABLED: "1",
};
await fs.mkdir(root + "/profile/data", { recursive: true });
const history = JSON.parse(
  gunzipSync(await fs.readFile("docs/qa/replay-review-native-main261-20261106/evidence/replay-requests.json.gz")),
);
const create = JSON.parse(history.find((x) => x.path === "/api/v1/replay/runs" && x.method === "POST").body);
async function call(path, data, raw = false) {
  const res = await fetch(
    q.s.backend + path,
    data === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": raw ? "text/csv" : "application/json" },
          body: raw ? data : JSON.stringify(data),
        },
  );
  const body = await res.text();
  assert.ok(res.ok, path + " " + res.status + " " + body.slice(0, 1200));
  return JSON.parse(body);
}
const runs = "/api/v1/replay/runs";
const getSnap = async (session) => (await call(runs + "/session/" + session)).snapshot;
const rows = [];
async function launch() {
  await q.launch();
  q.s.page.setDefaultTimeout(20000);
  assert.equal((await call("/health")).runtime_mode, "LOCAL_OFFLINE");
  await q.record("launch", q.s.identity);
}
async function createRun(label) {
  const id = (await call(runs, { ...create, name: label })).run.run_id;
  const path = runs + "/" + id;
  const catalog = await call(path + "/market-catalog");
  const entry = (symbol) =>
    catalog.entries.find((e) => e.identity.symbol === symbol && e.identity.market_type === "local_bar").identity;
  await call(path + "/markets", {
    ...entry("BTCUSDT"),
    catalog_epoch: catalog.catalog_epoch,
    base_interval: "1m",
    display_interval: "1m",
  });
  const first = (await call(path + "/tracks")).tracks[0];
  async function command(type, payload) {
    const snap = await getSnap(first.adapter_session_id),
      revision = snap.revision;
    return call(path + "/commands", {
      protocol: "replay.v3",
      run_id: id,
      command_id: crypto.randomUUID(),
      client_instance_id: "issue336-" + label,
      expected_revision: revision,
      expected_cursor: {
        virtual_time_ms: snap.cursor.virtual_time_ms,
        source_sequence: snap.cursor.source_sequence,
        revision,
      },
      type,
      payload,
    });
  }
  await command("acquire_controller", { takeover: false });
  const plan = await call(path + "/tracks/plan", { ...entry("ETHUSDT"), subscription_tier: "FULL" });
  await command("add_track", { plan_id: plan.plan_id });
  const tracks = (await call(path + "/tracks")).tracks;
  assert.equal(tracks.length, 2);
  for (const track of tracks) {
    const notes = path + "/tracks/" + track.track_id + "/notes";
    const before = await getSnap(track.adapter_session_id),
      { context } = await call(notes);
    const fields = { entryBasis: label + " " + track.symbol + " before fill" };
    const note = await call(notes, { id: "plan-" + track.track_id, fields, expectedRevision: 0, context });
    assert.equal(note.reviewNote, false);
    assert.deepEqual(await getSnap(track.adapter_session_id), before);
    rows.push({ label, run: id, notes, track, original: note });
  }
  const marker = await call(path + "/markers", {
    protocol: "replay.review.marker.v1",
    command_id: crypto.randomUUID(),
    text: label + " plans saved",
  });
  await command("step_base", { count: 1 });
  for (const [side, reduce_only] of [
    ["BUY", false],
    ["SELL", true],
  ]) {
    await command("place_order", {
      side,
      reduce_only,
      order_type: "MARKET",
      client_order_id: crypto.randomUUID(),
      quantity: "0.1",
      limit_price: null,
      stop_price: null,
    });
  }
  for (const row of rows.filter((row) => row.run === id)) {
    const { context } = await call(row.notes);
    const fields = { entryBasis: label + " " + row.track.symbol + " updated" };
    if (row.track.track_id === first.track_id) {
      for (const [kind, field] of [
        ["FILL", "replayFillIds"],
        ["TRADE", "replayTradeIds"],
      ]) {
        const result = await call(row.notes + "/link-options?kind=" + kind);
        assert.ok(result.links.length);
        fields[field] = JSON.stringify([result.links[0].id]);
      }
    }
    row.latest = await call(row.notes, { id: row.original.id, fields, expectedRevision: 1, context });
    assert.ok(row.latest.effectiveTimeMs > row.original.effectiveTimeMs);
  }
  await call(path + "/review", { event_id: marker.event_id });
  for (const row of rows.filter((row) => row.run === id)) {
    const before = await getSnap(row.track.adapter_session_id);
    const { context, notes } = await call(row.notes);
    assert.deepEqual(notes, [row.original]);
    const now = Date.now();
    row.supplement = await call(row.notes, {
      id: "review-" + row.track.track_id,
      fields: { entryBasis: label + " " + row.track.symbol + " retrospective" },
      expectedRevision: 0,
      context,
    });
    assert.ok(row.supplement.reviewNote);
    assert.equal(row.supplement.effectiveTimeMs, context.virtualTimeMs);
    assert.ok(row.supplement.updatedAtMs >= now - 10);
    assert.deepEqual(await getSnap(row.track.adapter_session_id), before);
  }
}
async function verifyRows() {
  for (const row of rows) {
    const historical = await call(row.notes);
    assert.deepEqual(historical.notes.map((n) => n.id).sort(), [row.original.id, row.supplement.id].sort());
    assert.deepEqual(
      historical.notes.find((n) => n.id === row.original.id),
      row.original,
    );
    assert.deepEqual(
      historical.notes.find((n) => n.id === row.supplement.id),
      row.supplement,
    );
    assert.deepEqual((await call(row.notes + "/" + row.original.id + "/versions")).versions, [row.original]);
    assert.deepEqual((await call(row.notes + "/" + row.original.id + "/versions?training_view=true")).versions, [
      row.latest,
      row.original,
    ]);
  }
}
async function openNotes(row) {
  await q.s.page.getByRole("navigation").first().waitFor({ timeout: 60000 });
  const url = new URL("/replay.html?run=" + row.run, q.s.page.url()).href;
  if (q.s.page.url() !== url) await q.s.page.goto(url, { waitUntil: "domcontentloaded" });
  const p = q.s.page.getByTestId("replay-notes-panel");
  const edit = p.getByRole("button", { name: /^(编辑|Edit)$/ }).first();
  await q.until(async () => {
    if (await edit.isVisible()) return true;
    for (const loc of [
      q.s.page.getByRole("button", { name: /^(回放笔记|Replay notes)$/i }).first(),
      p.locator("summary").first(),
    ])
      if (await loc.isVisible()) {
        await loc.click();
        break;
      }
    return false;
  }, 20000);
  return p;
}
async function checkReviewDraft(row, sequence, draftText) {
  const drawer = q.s.page.locator('[data-replay-panel="integrity"]');
  const toggle = q.s.page.locator('[data-replay-action="toggle-integrity"]');
  async function openDrawer() {
    if (await drawer.isVisible()) return;
    if (await toggle.isVisible()) await toggle.click();
    else {
      await q.s.page.getByRole("button", { name: "更多操作", exact: true }).click();
      await q.s.page.getByRole("menuitem", { name: /复盘/ }).click();
    }
  }
  await openDrawer();
  const starting = q.s.page.waitForResponse(
    (r) => r.request().method() === "POST" && new URL(r.url()).pathname === runs + "/" + row.run + "/review",
  );
  await drawer.getByRole("button", { name: "开始只读复盘", exact: true }).click();
  const started = await starting;
  assert.equal(started.status(), 200);
  const review = await started.json();
  const event = review.events.find((e) => e.timeline_sequence === sequence);
  assert.ok(event);
  await openDrawer();
  await drawer.getByRole("combobox", { name: "持久事件", exact: true }).selectOption(event.event_id);
  const move = q.s.page.waitForResponse(
    (r) => r.request().method() === "POST" && new URL(r.url()).pathname.endsWith("/cursor"),
  );
  await drawer.getByRole("button", { name: "跳转", exact: true }).click();
  const moved = await move;
  assert.equal(moved.status(), 200);
  const result = await moved.json();
  assert.equal((result.review ?? result).selected_event_id, event.event_id);
  await drawer.locator('[data-replay-action="close-integrity"]').click();
  const panel = q.s.page.getByTestId("replay-notes-panel");
  const disclosure = panel.locator("details");
  await disclosure.waitFor();
  if ((await disclosure.getAttribute("open")) === null) await disclosure.locator("summary").click();
  const add = panel.getByRole("button", { name: "新增复盘补记", exact: true });
  await add.waitFor();
  await q.until(() => add.isEnabled(), 20000);
  assert.equal(await panel.getByRole("button", { name: /恢复草稿/ }).count(), 0);
  assert.equal(await panel.locator("textarea").count(), 0);
  assert.ok(!(await panel.innerText()).includes(draftText));
  const expected = await call(row.notes);
  assert.equal(expected.context.timelineSequence, sequence);
  for (const note of expected.notes) {
    await panel.locator(`[data-note-id="${note.id}"]`).getByText(note.fields.entryBasis, { exact: true }).waitFor();
  }
  await q.screenshot("selected-review-event");
  await q.record("same-event-review-hides-live-draft", { sequence, event: event.event_id, selectedRun: row.run });
}
try {
  await launch();
  for (const [symbol, price] of [
    ["BTCUSDT", 100],
    ["ETHUSDT", 200],
  ]) {
    const csv =
      "time,open,high,low,close,volume\n" +
      Array.from({ length: 6000 }, (_, i) =>
        [start + 60000 * i, price, price + 2, price - 1, price + 1, 100].join(","),
      ).join("\n");
    await call(
      "/api/v1/local/imports/csv?" +
        new URLSearchParams({
          name: "Issue336 " + symbol,
          symbol,
          base_asset: symbol.slice(0, 3),
          quote_asset: "USDT",
          interval: "1m",
          timestamp_unit: "ms",
        }),
      csv,
      true,
    );
  }
  await createRun("A");
  await createRun("B");
  await verifyRows();
  await q.record("two-runs-two-markets", rows);
  const selected = rows[0],
    text = "draft from the original event after failed save";
  const panel = await openNotes(selected);
  await panel
    .locator('[data-note-id="' + selected.original.id + '"]')
    .getByRole("button", { name: /^(编辑|Edit)$/ })
    .click();
  const captureButton = panel.getByRole("button", { name: "截取当前图表", exact: true });
  const uploaded = q.s.page.waitForResponse(
    (r) => r.request().method() === "POST" && new URL(r.url()).pathname.endsWith("/note-captures"),
    { timeout: 30000 },
  );
  await captureButton.click({ timeout: 25000 });
  const upload = await uploaded;
  assert.equal(upload.status(), 200, await upload.text());
  const pixels = upload.request().postDataJSON().image;
  const captured = q.s.page.waitForResponse(
    (r) => r.request().method() === "POST" && new URL(r.url()).pathname === selected.notes,
  );
  await panel.getByRole("button", { name: "保存并关闭", exact: true }).click();
  const saved = await captured;
  assert.equal(saved.status(), 200, await saved.text());
  const withImage = await saved.json();
  assert.equal(withImage.revisionCount, 3);
  assert.equal(withImage.links.length, 2);
  assert.equal(withImage.screenshots.length, 1);
  const imagePath =
    selected.notes +
    "/" +
    selected.original.id +
    "/versions/3/screenshots/" +
    withImage.screenshots[0].id +
    "?training_view=true";
  assert.equal((await call(imagePath)).image, pixels);
  await panel
    .locator('[data-note-id="' + selected.original.id + '"]')
    .getByRole("button", { name: /^(编辑|Edit)$/ })
    .click();
  await panel.locator("textarea").fill(text);
  const live = await call(selected.notes + "?training_view=true");
  const latest = await call(selected.notes + "?training_view=true", {
    id: selected.original.id,
    expectedRevision: 3,
    context: live.context,
    fields: { entryBasis: "concurrent edit retained" },
  });
  const failed = q.s.page.waitForResponse(
    (r) => r.request().method() === "POST" && new URL(r.url()).pathname === selected.notes,
  );
  await panel.getByRole("button", { name: /^(保存|Save)$/ }).click();
  assert.equal((await failed).status(), 409);
  assert.equal(await panel.locator("textarea").inputValue(), text);
  const parent = await getSnap(selected.track.adapter_session_id);
  await q.record("failed-save-409", { note: latest.id, text });
  await q.quit();
  await q.exited();
  await launch();
  const restored = await openNotes(selected);
  await restored
    .getByRole("button", { name: /恢复草稿|Recover draft/i })
    .first()
    .click();
  assert.equal(await restored.locator("textarea").inputValue(), text);
  const after = await getSnap(selected.track.adapter_session_id);
  assert.deepEqual(after.components, parent.components);
  assert.deepEqual(after.cursor, parent.cursor);
  const versions = (await call(selected.notes + "/" + selected.original.id + "/versions?training_view=true"))
    .versions;
  assert.deepEqual(versions, [latest, withImage, selected.latest, selected.original]);
  assert.equal((await call(imagePath)).image, pixels);
  for (const row of rows.slice(1))
    assert.deepEqual((await call(row.notes + "/" + row.original.id + "/versions?training_view=true")).versions, [
      row.latest,
      row.original,
    ]);
  await q.record("restart", {
    draft: text,
    history: versions.map((n) => n.revisionCount),
    isolatedScopes: rows.length,
    accountAndCursorUnchanged: true,
    retainedPngBytes: Buffer.from(pixels.split(",")[1], "base64").length,
    retainedTradeAndFill: withImage.links.map((l) => l.kind),
  });
  await q.screenshot("restored");
  const keys = await q.s.page.evaluate(() =>
    Object.keys(localStorage)
      .filter((k) => k.startsWith("candlescope.replay-note-draft.v1:"))
      .map((k) => JSON.parse(localStorage.getItem(k))),
  );
  const draft = keys.find((value) => value.draft.includes(text));
  assert.ok(draft);
  await checkReviewDraft(selected, draft.context.timelineSequence, text);
  assert.deepEqual((await getSnap(selected.track.adapter_session_id)).components, parent.components);
  assert.deepEqual(q.s.receipt.errors, []);
  const health = await call("/health");
  assert.equal(health.local_offline.network.blocked_attempts, 0);
  await q.record("package", {
    asarSha256: createHash("sha256")
      .update(await fs.readFile(q.s.identity.resources + "/app.asar"))
      .digest("hex"),
    offlineBlockedAttempts: health.local_offline.network.blocked_attempts,
  });
  await q.quit();
  await q.exited();
  q.s.receipt.passed = true;
  await q.save();
} catch (e) {
  console.error(e);
  q.s.receipt.failure = String(e.stack);
  await q.save();
  try {
    await fs.writeFile(root + "/page.txt", await q.s.page.locator("body").ariaSnapshot({ timeout: 2000 }));
  } catch {}
  try {
    await q.quit();
    await q.exited();
  } catch {}
  process.exitCode = 1;
}
