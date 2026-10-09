import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

test("packaged smoke waits for initial load before navigating on both launches", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "candlescope-smoke-test-"));
  try {
    const output = path.join(root, "evidence");
    const module = path.join(root, "playwright.cjs");
    const setup = path.join(root, "fetch.mjs");
    writeFileSync(setup, 'globalThis.fetch = async () => new Response(JSON.stringify({ desktop_instance_id: "fixture" }), { status: 200 });\n');
    writeFileSync(module, `
      const assert = require("node:assert/strict");
      const path = require("node:path");
      let launches = 0;
      exports._electron = { launch: async ({ env }) => {
        launches++;
        let loaded = false;
        const resources = path.join(env.CANDLESCOPE_DESKTOP_USER_DATA, "resources");
        const page = {
          setDefaultTimeout() {}, setDefaultNavigationTimeout() {},
          async waitForURL(predicate, options) {
            assert.equal(predicate(new URL("http://127.0.0.1:12345/")), true);
            assert.equal(predicate(new URL("http://127.0.0.1:12345/index.html")), true);
            assert.equal(predicate(new URL("about:blank")), false);
            assert.equal(options.waitUntil, "load");
            loaded = true;
          },
          async waitForFunction() {},
          async evaluate() { return { sidecar: { running: true,
            command: path.join(resources, "python-runtime", "python"), healthUrl: "http://127.0.0.1:12346/health" } }; },
          url() { return "http://127.0.0.1:12345/index.html"; },
          async goto() { assert.ok(loaded, "navigation must not abort the host's initial loadURL"); },
          locator() { return { count: async () => 0 }; },
          async title() { return "CandleScope"; },
          async screenshot() {},
        };
        return {
          firstWindow: async () => page,
          evaluate: async () => ({ packaged: true, userData: env.CANDLESCOPE_DESKTOP_USER_DATA, resources }),
          close: async () => { assert.ok(loaded); },
        };
      }};
      process.on("exit", () => assert.equal(launches, 2));
    `);
    const result = spawnSync(process.execPath, [
      "--import", setup, fileURLToPath(new URL("./desktop-package-smoke.mjs", import.meta.url)),
      "--executable", path.join(root, "CandleScope"), "--playwright-module", module, "--out", output,
    ], { encoding: "utf8", timeout: 30_000 });
    assert.equal(result.status, 0, result.stdout + result.stderr);
    const report = JSON.parse(readFileSync(path.join(output, "report.json"), "utf8"));
    assert.equal(report.result, "passed");
    assert.equal(report.launches.length, 2);
    assert.equal(report.launches[1].pages.length, 3);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
