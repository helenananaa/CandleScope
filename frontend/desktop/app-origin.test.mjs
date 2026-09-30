import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import test from "node:test";
import http from "node:http";
import { isTrustedAppUrl, startDesktopAssetServer } from "./app-origin.mjs";

test("occupied asset port falls back to an owned listener and preserves the existing service", async () => {
  const occupied = http.createServer((_req, res) => res.end("existing service"));
  await new Promise(resolve => occupied.listen(0, "127.0.0.1", resolve));
  const port = occupied.address().port;
  const root = await mkdtemp(path.join(os.tmpdir(), "candlescope-assets-busy-"));
  await writeFile(path.join(root, "index.html"), "desktop");
  let server;
  try {
    server = await startDesktopAssetServer(root, { port });
    assert.notEqual(Number(new URL(server.appUrl).port), port);
    assert.equal(await (await fetch(server.appUrl)).text(), "desktop");
    assert.equal(await (await fetch(`http://127.0.0.1:${port}`)).text(), "existing service");
    assert.equal(isTrustedAppUrl(`http://127.0.0.1:${port}/`, server.appUrl), false);
  } finally {
    await server?.close();
    occupied.closeAllConnections();
    await new Promise(resolve => occupied.close(resolve));
  }
});

test("packaged assets have an exact loopback origin and do not expose sibling files", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "candlescope-assets-"));
  const dist = path.join(root, "dist");
  await mkdir(dist);
  await writeFile(path.join(dist, "index.html"), "main");
  await writeFile(path.join(dist, "replay.html"), "replay");
  await writeFile(path.join(root, "private.txt"), "private");
  const server = await startDesktopAssetServer(dist, { port: 0 });
  try {
    assert.equal(await (await fetch(server.appUrl)).text(), "main");
    assert.equal(await (await fetch(new URL("replay.html", server.appUrl))).text(), "replay");
    assert.equal((await fetch(`${server.appUrl}%2e%2e%2fprivate.txt`)).status, 403);
    const forbiddenHostStatus = await new Promise((resolve, reject) => {
      http.get(server.appUrl, { headers: { Host: "attacker.example" } }, (response) => {
        response.resume(); resolve(response.statusCode);
      }).on("error", reject);
    });
    assert.equal(forbiddenHostStatus, 403);
    assert.equal(isTrustedAppUrl(new URL("replay.html?run=one", server.appUrl).href, server.appUrl), true);
    for (const url of ["about:blank", "file:///C:/app/index.html", "https://attacker.example/", `${server.appUrl}assets/plugin.html`]) {
      assert.equal(isTrustedAppUrl(url, server.appUrl), false);
    }
  } finally { await server.close(); }
});
