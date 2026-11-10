import assert from "node:assert/strict";
import { mkdtemp, rm, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { DesktopStrategyStorage } from "./strategy-storage.mjs";

test("profile state survives asset-port changes and queued writes finish before shutdown", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "cs-strategy-storage-"));
  try {
    const file = path.join(root, "strategy-storage.json");
    const first = new DesktopStrategyStorage(file);
    await first.load();
    const writes = [first.setItem("candlescope-strategy-drafts-v1", '{"fast":4}'),
      first.setItem("candlescope:strategy-research:v1", '{"draftId":"saved","runId":"completed"}')];
    assert.equal(first.getItem("candlescope-strategy-drafts-v1"), '{"fast":4}');
    await first.flush();
    await Promise.all(writes);
    const restarted = new DesktopStrategyStorage(file);
    await restarted.load();
    assert.equal(restarted.getItem("candlescope-strategy-drafts-v1"), '{"fast":4}');
    assert.equal(restarted.getItem("candlescope:strategy-research:v1"), '{"draftId":"saved","runId":"completed"}');
    assert.deepEqual(Object.keys(JSON.parse(await readFile(file, "utf8")).values).sort(),
      ["candlescope-strategy-drafts-v1", "candlescope:strategy-research:v1"].sort());
    assert.throws(() => restarted.setItem("../../secret", "bad"), /Invalid/);
    assert.throws(() => restarted.getItem("access-token"), /Unsupported/);
    assert.throws(() => restarted.setItem("candlescope-strategy-drafts-v1", "x".repeat(17 * 1024 * 1024)), /Invalid/);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test("research handoffs survive a reload within a bounded desktop namespace", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "cs-research-return-"));
  try {
    const file = path.join(root, "strategy-storage.json");
    const store = new DesktopStrategyStorage(file);
    const key = index => "candlescope:research-return:request-" + index;
    const writes = Array.from({length: 65}, (_, index) => store.setItem(key(index), JSON.stringify({index})));
    await Promise.all(writes);
    const restored = new DesktopStrategyStorage(file);
    await restored.load();
    assert.equal(restored.getItem(key(0)), null);
    assert.equal(restored.getItem(key(64)), '{"index":64}');
    assert.throws(() => restored.setItem("candlescope:research-return:../secrets", "{}"), /Invalid/);
    assert.throws(() => restored.setItem(key(65), "x".repeat(2049)), /Invalid/);
  } finally { await rm(root, {recursive: true, force: true}); }
});
