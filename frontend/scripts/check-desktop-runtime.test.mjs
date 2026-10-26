import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { Arch } from "builder-util";
import checkDesktopRuntime from "./check-desktop-runtime.cjs";

function fixture(t, platform = "darwin", arch = "arm64") {
  const projectDir = fs.mkdtempSync(path.join(os.tmpdir(), "candlescope-package-check-"));
  t.after(() => fs.rmSync(projectDir, { recursive: true, force: true }));
  const root = path.join(projectDir, ".desktop-runtime", "runtime");
  const pluginsRoot = path.join(root, "plugins");
  fs.mkdirSync(pluginsRoot, { recursive: true });
  fs.writeFileSync(path.join(root, "manifest.json"), JSON.stringify({ platform, arch }));
  const bytes = Buffer.from("isolated Pine bundle fixture");
  const plugin = {
    runtimeId: "candlescope.pine-compat",
    filename: "pine.cspkg",
    size: bytes.length,
    sha256: `sha256:${createHash("sha256").update(bytes).digest("hex")}`,
  };
  fs.writeFileSync(path.join(pluginsRoot, plugin.filename), bytes);
  const writeManifest = (value) => fs.writeFileSync(
    path.join(pluginsRoot, "manifest.json"), JSON.stringify(value),
  );
  writeManifest({ schemaVersion: 2, plugins: [plugin] });
  return {
    context: { packager: { projectDir }, electronPlatformName: platform, arch: Arch[arch] },
    plugin, pluginsRoot, writeManifest,
  };
}

for (const [platform, arch] of [["darwin", "arm64"], ["darwin", "x64"], ["win32", "x64"], ["linux", "x64"]]) {
  test(`packaging accepts the single verified Pine runtime for ${platform}/${arch}`, async (t) => {
    const { context } = fixture(t, platform, arch);
    await checkDesktopRuntime(context);
  });
}

test("packaging rejects absent, malformed, duplicate, and retired runtime selections", async (t) => {
  const { context, plugin, writeManifest } = fixture(t);
  for (const plugins of [undefined, null, {}, [], [null], [plugin, plugin],
    [{ ...plugin, runtimeId: "candlescope.pyne" }],
    [plugin, { ...plugin, runtimeId: "candlescope.pyne" }]]) {
    writeManifest({ schemaVersion: 2, plugins });
    await assert.rejects(checkDesktopRuntime(context), /bundled Pine runtime/);
  }
  writeManifest({ schemaVersion: 1, plugins: [plugin] });
  await assert.rejects(checkDesktopRuntime(context), /bundled Pine runtime/);
});

test("packaging still enforces bundle size and hash", async (t) => {
  const { context, plugin, pluginsRoot, writeManifest } = fixture(t);
  writeManifest({ schemaVersion: 2, plugins: [{ ...plugin, size: plugin.size + 1 }] });
  await assert.rejects(checkDesktopRuntime(context), /Bundled runtime hash mismatch/);
  writeManifest({ schemaVersion: 2, plugins: [plugin] });
  fs.writeFileSync(path.join(pluginsRoot, plugin.filename), Buffer.alloc(plugin.size));
  await assert.rejects(checkDesktopRuntime(context), /Bundled runtime hash mismatch/);
});

test("packaging still rejects a Python runtime for another architecture or platform", async (t) => {
  const { context } = fixture(t);
  await assert.rejects(checkDesktopRuntime({ ...context, arch: Arch.x64 }), /does not match/);
  await assert.rejects(checkDesktopRuntime({ ...context, electronPlatformName: "win32" }), /does not match/);
});
