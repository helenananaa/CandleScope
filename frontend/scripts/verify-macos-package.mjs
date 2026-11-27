import assert from "node:assert/strict";
import { access, constants, readFile, readdir, realpath, lstat } from "node:fs/promises";
import { createHash } from "node:crypto";
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
// The proxy core ships with its upstream license and source pointer, as prepare-mihomo.py pins them.
const mihomo = path.join(runtime, "mihomo");
const pins = await readFile(path.join(import.meta.dirname, "prepare-mihomo.py"), "utf8");
const pin = (pattern, name) => {
  const match = pins.match(pattern);
  assert.ok(match, `prepare-mihomo.py no longer declares ${name}`);
  return match[1];
};
const mihomoVersion = pin(/^VERSION = "([^"]+)"$/m, "VERSION");
const licenseDigest = pin(/^LICENSE_SHA256 = "([0-9a-f]{64})"$/m, "LICENSE_SHA256");
const machine = arch === "x64" ? "x86_64" : arch;
const [, asset, assetDigest] = pins.match(
  new RegExp(`\\("darwin", "${machine}"\\): \\("([^"]+)", "gz", "([0-9a-f]{64})"\\)`),
) ?? assert.fail(`prepare-mihomo.py has no darwin ${machine} asset`);
await access(path.join(mihomo, "mihomo"), constants.X_OK);
const license = await readFile(path.join(mihomo, "LICENSE"));
assert.equal(createHash("sha256").update(license).digest("hex"), licenseDigest, "Bundled Mihomo LICENSE is not the pinned upstream text");
const source = await readFile(path.join(mihomo, "SOURCE.txt"), "utf8");
assert.ok(source.startsWith(`Mihomo ${mihomoVersion}\n`), `Bundled Mihomo SOURCE.txt does not name ${mihomoVersion}`);
for (const line of [`/tree/${mihomoVersion}`, `/archive/refs/tags/${mihomoVersion}.tar.gz`,
  `Unmodified release artifact: mihomo-${asset}-${mihomoVersion}.gz`, `SHA-256: ${assetDigest}`]) {
  assert.ok(source.includes(line), `Bundled Mihomo SOURCE.txt lacks ${JSON.stringify(line)}`);
}
for (const executable of [path.join(app, "Contents", "MacOS", "CandleScope"), python, path.join(mihomo, "mihomo")]) {
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
console.log(`Verified relocated ${arch} app, bundled Python/dependencies, Mihomo ${mihomoVersion} with license and source, symlinks and ad-hoc signature`);
