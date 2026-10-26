import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { test } from "node:test";
import { prepareDesktopRuntime } from "./desktop-runtime-cache.mjs";

async function fixture(t) {
  const cache = await fs.mkdtemp(path.join(os.tmpdir(), "candlescope-runtime-cache-"));
  t.after(() => fs.rm(cache, { recursive: true, force: true }));
  for (const name of ["runtime", "previous-100", "previous-200", "downloads", "control", "plugin-build", "staging-other-build"]) {
    await fs.mkdir(path.join(cache, name));
    await fs.writeFile(path.join(cache, name, "marker"), name);
  }
  return cache;
}

test("repeated successful builds retain only the immediate rollback runtime", async t => {
  const cache = await fixture(t);
  for (const value of ["first", "second"]) {
    await prepareDesktopRuntime(cache, staging => fs.writeFile(path.join(staging, "marker"), value));
  }
  const names = await fs.readdir(cache);
  const backups = names.filter(name => name.startsWith("previous-"));
  assert.equal(backups.length, 1);
  assert.equal(await fs.readFile(path.join(cache, backups[0], "marker"), "utf8"), "first");
  assert.equal(await fs.readFile(path.join(cache, "runtime", "marker"), "utf8"), "second");
  for (const name of ["downloads", "control", "plugin-build", "staging-other-build"]) {
    assert.equal(await fs.readFile(path.join(cache, name, "marker"), "utf8"), name);
  }
  assert.deepEqual(names.filter(name => name.startsWith("staging-")), ["staging-other-build"]);
});

test("failed build removes its partial files and preserves the active runtime and backups", async t => {
  const cache = await fixture(t);
  await assert.rejects(prepareDesktopRuntime(cache, async staging => {
    await fs.writeFile(path.join(staging, "partial"), "incomplete");
    throw new Error("dependency installation failed");
  }), /dependency installation failed/);
  assert.equal(await fs.readFile(path.join(cache, "runtime", "marker"), "utf8"), "runtime");
  assert.deepEqual((await fs.readdir(cache)).sort(), ["control", "downloads", "plugin-build", "previous-100", "previous-200", "runtime", "staging-other-build"]);
});

test("failed promotion restores the previous active runtime", async t => {
  const cache = await fixture(t);
  await assert.rejects(prepareDesktopRuntime(cache, staging => fs.rm(staging, { recursive: true })), { code: "ENOENT" });
  assert.equal(await fs.readFile(path.join(cache, "runtime", "marker"), "utf8"), "runtime");
  assert.deepEqual((await fs.readdir(cache)).sort(), ["control", "downloads", "plugin-build", "previous-100", "previous-200", "runtime", "staging-other-build"]);
});

test("a first installation retains the newest numbered rollback directory", async t => {
  const cache = await fixture(t);
  const runtime = path.resolve(cache, "runtime");
  assert.equal(path.dirname(runtime), cache);
  await fs.rm(runtime, { recursive: true });
  await fs.rename(path.join(cache, "previous-200"), path.join(cache, "previous-1000"));
  await prepareDesktopRuntime(cache, staging => fs.writeFile(path.join(staging, "marker"), "first"));
  assert.deepEqual((await fs.readdir(cache)).filter(name => name.startsWith("previous-")), ["previous-1000"]);
  assert.equal(await fs.readFile(path.join(cache, "runtime", "marker"), "utf8"), "first");
});

test("an existing promotion lock prevents replacement and pruning without removing its owner", async t => {
  const cache = await fixture(t);
  const lockPath = path.join(cache, "runtime-promotion.lock");
  const owner = JSON.stringify({ pid: process.pid });
  await fs.writeFile(lockPath, owner);
  await assert.rejects(prepareDesktopRuntime(cache, staging => fs.writeFile(path.join(staging, "marker"), "candidate")),
    /Runtime promotion is locked/);
  assert.equal(await fs.readFile(lockPath, "utf8"), owner);
  for (const name of ["runtime", "previous-100", "previous-200", "downloads", "control", "plugin-build", "staging-other-build"]) {
    assert.equal(await fs.readFile(path.join(cache, name, "marker"), "utf8"), name);
  }
  assert.deepEqual((await fs.readdir(cache)).filter(name => name.startsWith("staging-")), ["staging-other-build"]);
});

test("the preparation entry point cleans staging when uv cannot start", async t => {
  const fixtureRoot = await fixture(t);
  const frontend = path.join(fixtureRoot, "frontend");
  const scripts = path.join(frontend, "scripts");
  const cache = path.join(frontend, ".desktop-runtime");
  await fs.mkdir(scripts, { recursive: true });
  await fs.mkdir(path.join(cache, "runtime"), { recursive: true });
  await fs.writeFile(path.join(cache, "runtime", "marker"), "working");
  for (const name of ["prepare-desktop-runtime.mjs", "desktop-runtime-cache.mjs"]) {
    await fs.copyFile(new URL(name, import.meta.url), path.join(scripts, name));
  }
  const result = spawnSync(process.execPath, [path.join(scripts, "prepare-desktop-runtime.mjs")], {
    env: { ...process.env, CANDLESCOPE_UV: path.join(fixtureRoot, "missing-uv") },
    encoding: "utf8", windowsHide: true,
  });
  assert.equal(result.status, 1, result.stderr);
  assert.match(result.stderr, /ENOENT/);
  assert.deepEqual(await fs.readdir(cache), ["runtime"]);
  assert.equal(await fs.readFile(path.join(cache, "runtime", "marker"), "utf8"), "working");
});
