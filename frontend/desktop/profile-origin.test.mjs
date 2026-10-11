import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import http from "node:http";
import test from "node:test";
import { startProfileAssetServer } from "./profile-origin.mjs";

async function fixture(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), "candlescope-profile-origin-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const dist = path.join(root, "dist");
  await mkdir(dist); await writeFile(path.join(dist, "index.html"), "app");
  const occupied = http.createServer((_req, res) => res.end("other app"));
  await new Promise(resolve => occupied.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise(resolve => { occupied.closeAllConnections(); occupied.close(resolve); }));
  return { root, dist, port: occupied.address().port };
}

test("new profiles get distinct origins, then retain them across reversed startup order", async t => {
  const { root, dist, port } = await fixture(t);
  const a = { userData: path.join(root, "a"), port }, b = { userData: path.join(root, "b"), port };
  const first = await startProfileAssetServer(dist, a), second = await startProfileAssetServer(dist, b);
  assert.notEqual(first.appUrl, second.appUrl);
  assert.notEqual(Number(new URL(first.appUrl).port), port);
  await first.close(); await second.close();
  const secondAgain = await startProfileAssetServer(dist, b), firstAgain = await startProfileAssetServer(dist, a);
  try {
    assert.equal(secondAgain.appUrl, second.appUrl); assert.equal(firstAgain.appUrl, first.appUrl);
    assert.equal(await (await fetch(firstAgain.appUrl)).text(), "app");
    await assert.rejects(startProfileAssetServer(dist, a), { code: "DESKTOP_ORIGIN_UNAVAILABLE" });
    assert.equal(JSON.parse(await readFile(path.join(a.userData, "desktop-origin-v1.json"))).port, Number(new URL(first.appUrl).port));
  } finally { await firstAgain.close(); await secondAgain.close(); }
});

test("legacy Chromium storage cannot silently switch origin when its port is occupied", async t => {
  const { root, dist, port } = await fixture(t);
  const userData = path.join(root, "legacy");
  await mkdir(path.join(userData, "Local Storage"), { recursive: true });
  await assert.rejects(startProfileAssetServer(dist, { userData, port }), { code: "DESKTOP_ORIGIN_UNAVAILABLE" });
  await assert.rejects(readFile(path.join(userData, "desktop-origin-v1.json")), { code: "ENOENT" });
  assert.equal(await (await fetch(`http://127.0.0.1:${port}`)).text(), "other app");
});

test("corrupt origin metadata is rejected rather than replacing the profile origin", async t => {
  const { root, dist, port } = await fixture(t);
  const userData = path.join(root, "bad"); await mkdir(userData);
  const file = path.join(userData, "desktop-origin-v1.json");
  await writeFile(file, '{"schemaVersion":1,"port":0}');
  await assert.rejects(startProfileAssetServer(dist, { userData, port }), /Invalid saved desktop origin/);
  assert.equal(await readFile(file, "utf8"), '{"schemaVersion":1,"port":0}');
});
