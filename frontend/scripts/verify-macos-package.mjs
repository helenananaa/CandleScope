import assert from "node:assert/strict";
import { readFile, readdir, realpath, lstat } from "node:fs/promises";
import path from "node:path";
import { execFileSync } from "node:child_process";

const app = await realpath(process.argv[2]);
const arch = process.argv[3];
assert.ok(["arm64", "x64"].includes(arch), "Expected arm64 or x64");
const resources = path.join(app, "Contents", "Resources");
const runtime = path.join(resources, "python-runtime");
const python = path.join(runtime, "python", "bin", "python3");
const manifest = JSON.parse(await readFile(path.join(runtime, "manifest.json"), "utf8"));
assert.equal(manifest.platform, "darwin");
assert.equal(manifest.arch, arch);
for (const executable of [path.join(app, "Contents", "MacOS", "CandleScope"), python]) {
  const architectures = execFileSync("lipo", ["-archs", executable], { encoding: "utf8" }).trim().split(/\s+/);
  assert.ok(architectures.includes(arch === "x64" ? "x86_64" : arch), `${executable}: ${architectures}`);
}
// A relocated bundle must not contain symlinks back to the CI staging directory.
async function verifyLinks(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const filename = path.join(directory, entry.name);
    if ((await lstat(filename)).isSymbolicLink()) {
      const target = await realpath(filename);
      assert.ok(target.startsWith(`${app}${path.sep}`), `External bundle symlink: ${filename} -> ${target}`);
    } else if (entry.isDirectory()) await verifyLinks(filename);
  }
}
await verifyLinks(app);
const env = { ...process.env, PYTHONPATH: path.join(runtime, "site-packages"), PYTHONNOUSERSITE: "1", PYTHONDONTWRITEBYTECODE: "1" };
delete env.PYTHONHOME;
execFileSync(python, ["-c", "import platform, fastapi, uvicorn, numpy, pandas, orjson, ccxt, exchange_calendars, pyarrow.parquet, candlescope_plugin_sdk, candlescope_backtest_sdk; assert platform.machine() == " + JSON.stringify(arch === "x64" ? "x86_64" : arch)], { env, stdio: "inherit", cwd: resources });
execFileSync("codesign", ["--verify", "--deep", "--strict", app], { stdio: "inherit" });
console.log(`Verified relocated ${arch} app, bundled Python/dependencies, symlinks and ad-hoc signature`);
