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
  const controlRoot = path.join(projectDir, ".desktop-runtime", "control");
  fs.mkdirSync(controlRoot, { recursive: true });
  const controlBytes = Buffer.from("isolated desktop control adapter fixture");
  fs.writeFileSync(path.join(controlRoot, "cli.mjs"), controlBytes);
  fs.writeFileSync(path.join(controlRoot, "manifest.json"), JSON.stringify({
    schema: "candlescope.control-bundle/1",
    sha256: createHash("sha256").update(controlBytes).digest("hex"),
  }));
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
  const pythonBytes = Buffer.from("isolated Python indicator bundle fixture");
  const python = { schema: "candlescope.bundled-unified-python/1", filename: "python.cspkg", size: pythonBytes.length,
    sha256: `sha256:${createHash("sha256").update(pythonBytes).digest("hex")}` };
  fs.writeFileSync(path.join(pluginsRoot, python.filename), pythonBytes);
  const writePine = value => fs.writeFileSync(path.join(pluginsRoot, "unified-pine.json"), JSON.stringify(value));
  const pine = { schema: "candlescope.bundled-unified-pine/1", filename: plugin.filename, size: plugin.size, sha256: plugin.sha256 };
  const writePython = value => fs.writeFileSync(path.join(pluginsRoot, "unified-python.json"), JSON.stringify(value));
  writePython(python);
  writePine(pine);
  return {
    context: { packager: { projectDir }, electronPlatformName: platform, arch: Arch[arch] },
    pine, python, pluginsRoot, writePython, writePine, controlRoot,
  };
}

for (const [platform, arch] of [["darwin", "arm64"], ["darwin", "x64"], ["win32", "x64"], ["linux", "x64"]]) {
  test(`packaging accepts both verified Pine and Python runtimes for ${platform}/${arch}`, async (t) => {
    const { context } = fixture(t, platform, arch);
    await checkDesktopRuntime(context);
  });
}

test("packaging rejects missing unified descriptors and retired script manifests", async (t) => {
  const { context, pluginsRoot, python, writePython } = fixture(t);
  fs.unlinkSync(path.join(pluginsRoot, "unified-python.json"));
  await assert.rejects(checkDesktopRuntime(context), /bundled first-party runtime/);
  writePython({ ...python, schema: "candlescope.bundled-unified-pyne/1" });
  await assert.rejects(checkDesktopRuntime(context), /descriptor is invalid/);
  writePython(python);
  fs.writeFileSync(path.join(pluginsRoot, "manifest.json"), JSON.stringify({ schemaVersion: 2 }));
  await assert.rejects(checkDesktopRuntime(context), /Retired script runtime manifest/);
});

test("packaging still enforces bundle size and hash", async (t) => {
  const { context, pine, python, pluginsRoot, writePine } = fixture(t);
  writePine({ ...pine, size: pine.size + 1 });
  await assert.rejects(checkDesktopRuntime(context), /Bundled runtime hash mismatch/);
  writePine(pine);
  fs.writeFileSync(path.join(pluginsRoot, python.filename), Buffer.alloc(python.size));
  await assert.rejects(checkDesktopRuntime(context), /Bundled runtime hash mismatch: candlescope.python-indicator/);
});

test("packaging rejects a modified desktop control adapter", async (t) => {
  const { context, controlRoot } = fixture(t);
  fs.appendFileSync(path.join(controlRoot, "cli.mjs"), "tampered");
  await assert.rejects(checkDesktopRuntime(context), /Prepare the control adapter/);
});

test("packaging still rejects a Python runtime for another architecture or platform", async (t) => {
  const { context } = fixture(t);
  await assert.rejects(checkDesktopRuntime({ ...context, arch: Arch.x64 }), /does not match/);
  await assert.rejects(checkDesktopRuntime({ ...context, electronPlatformName: "win32" }), /does not match/);
});
