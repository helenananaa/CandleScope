import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, writeFile, readFile, rm } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";
import { TrustedDesktopExtensionHost } from "./trusted-extension-host.mjs";

test("desktop loads only the approved digest and disposes owned native hooks", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "candlescope-extension-"));
  try {
    const source = "export function activate(ctx) { ctx.host.calls.push('activate'); ctx.track(() => ctx.host.calls.push('dispose')); }";
    await writeFile(path.join(root, "main.mjs"), source);
    const context = { host: { calls: [] } };
    const host = new TrustedDesktopExtensionHost({ markerPath: path.join(root, "marker.json"), context });
    const record = { root, digest: "a".repeat(64), generation: 3, manifest: { id: "example.desktop", version: "1.0.0", apiVersion: 1, trust: "full-trust", entries: { desktop: "main.mjs" } }, files: { "main.mjs": createHash("sha256").update(source).digest("hex") } };
    await host.start({ active: [record] });
    assert.deepEqual(context.host.calls, ["activate"]);
    assert.deepEqual(host.diagnostics().active, [{ id: "example.desktop", digest: record.digest, generation: 3, version: "1.0.0" }]);
    host.diagnostics().active[0].version = "mutated";
    assert.equal(host.diagnostics().active[0].version, "1.0.0");
    await host.stop();
    assert.deepEqual(context.host.calls, ["activate", "dispose"]);
    assert.deepEqual(host.diagnostics().active, []);
    await writeFile(path.join(root, "main.mjs"), "throw new Error('tampered')");
    await host.start({ active: [record] });
    assert.match(host.errors["example.desktop"], /integrity/);
    assert.deepEqual(context.host.calls, ["activate", "dispose"]);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test("desktop safe mode never reads or executes declared modules", async () => {
  const host = new TrustedDesktopExtensionHost({ markerPath: "unused", context: {} });
  await host.start({ safeMode: true, active: [{ root: "missing" }] });
  assert.deepEqual(host.loaded, []);
  assert.equal(host.diagnostics().safeMode, true);
});

test("an interrupted process retains its marker and only a new approval retries it", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "candlescope-extension-crash-"));
  try {
    const source = "export function activate(ctx) { if (!ctx.host?.recovered) process.exit(23); ctx.host.calls.push('retried'); }";
    await writeFile(path.join(root, "main.mjs"), source);
    const markerPath = path.join(root, "marker.json");
    const record = { root, digest: "b".repeat(64), generation: 4, manifest: { id: "example.crash", version: "1.0.0", apiVersion: 1, trust: "full-trust", entries: { desktop: "main.mjs" } }, files: { "main.mjs": createHash("sha256").update(source).digest("hex") } };
    const child = spawnSync(process.execPath, ["--input-type=module", "-e", `
      import { TrustedDesktopExtensionHost } from ${JSON.stringify(new URL("./trusted-extension-host.mjs", import.meta.url).href)};
      const host = new TrustedDesktopExtensionHost({ markerPath: ${JSON.stringify(markerPath)}, context: {} });
      await host.start({ active: [${JSON.stringify(record)}] });
    `], { encoding: "utf8", timeout: 10_000, windowsHide: true });
    assert.equal(child.status, 23, child.stderr);
    assert.deepEqual(JSON.parse(await readFile(markerPath, "utf8")), { digest: record.digest, generation: 4 });
    const context = { host: { recovered: true, calls: [] } };
    const host = new TrustedDesktopExtensionHost({ markerPath, context });
    await host.start({ active: [record] });
    assert.match(host.errors["example.crash"], /Previous startup interrupted/);
    assert.deepEqual(context.host.calls, []);
    const retry = new TrustedDesktopExtensionHost({ markerPath, context });
    await retry.start({ active: [{ ...record, generation: 5 }] });
    assert.deepEqual(context.host.calls, ["retried"]);
    // Preserve the previous failed activation while a deliberate retry succeeds.
    assert.deepEqual(JSON.parse(await readFile(markerPath, "utf8")), { digest: record.digest, generation: 4 });
    await retry.stop();
  } finally { await rm(root, { recursive: true, force: true }); }
});
