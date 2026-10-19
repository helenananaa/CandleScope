import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, rename, rm, symlink, utimes, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import test from "node:test";

const compile = createRequire(import.meta.url)("./compile-desktop-python.cjs");
const probe = spawnSync("python3", ["-I", "-c", "import sys; print(sys.executable)"], { encoding: "utf8" });
const python = probe.status === 0 ? probe.stdout.trim() : null;
const skip = process.platform === "win32" ? "POSIX relocation fixture; Windows package is validated separately" : !python ? "Python 3 is required for the real compilation fixture" : false;
const hash = (bytes) => createHash("sha256").update(bytes).digest("hex");
function run(args) {
  const result = spawnSync(python, args, { encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  return result.stdout.trim();
}

test("packaging replaces timestamp caches and keeps imported bytecode sealed after relocation", { skip }, async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "candlescope-bytecode-"));
  let currentRoot = root;
  try {
    const resources = path.join(root, "CandleScope.app", "Contents", "Resources");
    const runtime = path.join(resources, "python-runtime");
    const lib = path.join(runtime, "python", "lib");
    for (const dir of [lib, path.join(runtime, "python", "bin"), path.join(runtime, "site-packages"), path.join(resources, "backend", "app"), path.join(resources, "packages")]) await mkdir(dir, { recursive: true });
    await symlink(python, path.join(runtime, "python", "bin", "python3"));
    const source = path.join(lib, "sealed_fixture.py");
    await writeFile(source, "ANSWER = 42\n");
    await utimes(source, 1_792_366_001, 1_792_366_001);
    const cache = run(["-I", "-c", "import py_compile,sys; print(py_compile.compile(sys.argv[1],doraise=True,invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP))", source]);
    assert.equal((await readFile(cache)).readUInt32LE(4), 0, "fixture starts with an otherwise current timestamp cache");

    await compile({ electronPlatformName: "darwin", appOutDir: root, packager: { appInfo: { productFilename: "CandleScope" } } });
    const signed = await readFile(cache);
    assert.equal(signed.readUInt32LE(4), 3, "existing caches must become checked-hash caches before signing");

    currentRoot = `${root}-relocated`;
    await rename(root, currentRoot);
    const relativeSource = path.relative(root, source);
    const relativeCache = path.relative(root, cache);
    // Archive extraction can round a source timestamp even when its bytes match.
    await utimes(path.join(currentRoot, relativeSource), 1_792_366_002, 1_792_366_002);
    assert.equal(run(["-I", "-c", "import sys; sys.path.insert(0,sys.argv[1]); import sealed_fixture; print(sealed_fixture.ANSWER)", path.join(currentRoot, path.relative(root, lib))]), "42");
    assert.equal(hash(await readFile(path.join(currentRoot, relativeCache))), hash(signed), "a normal isolated import must not rewrite signed cache bytes");
  } finally {
    await rm(currentRoot, { recursive: true, force: true });
    if (currentRoot !== root) await rm(root, { recursive: true, force: true });
  }
});
