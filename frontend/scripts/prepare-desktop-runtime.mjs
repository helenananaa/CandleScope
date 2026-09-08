import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repo = path.dirname(frontend);
const cache = path.join(frontend, ".desktop-runtime");
const staging = path.join(cache, `staging-${Date.now()}`);
const downloads = path.join(cache, "downloads");
const uv = process.env.CANDLESCOPE_UV || "uv";
const run = (command, args, options = {}) => {
  const result = spawnSync(command, args, { cwd: repo, stdio: "inherit", ...options });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${command} exited with ${result.status}`);
  return result;
};

await fs.mkdir(staging, { recursive: true });
run(uv, ["python", "install", "3.12", "--install-dir", downloads, "--no-bin", "--no-registry"]);
const found = spawnSync(uv, ["python", "find", "3.12", "--managed-python"], {
  encoding: "utf8", env: { ...process.env, UV_PYTHON_INSTALL_DIR: downloads },
});
if (found.status !== 0) throw new Error(found.stderr || "Managed Python was not found");
const executable = await fs.realpath(found.stdout.trim());
const sourceRoot = process.platform === "win32" ? path.dirname(executable) : path.dirname(path.dirname(executable));
if (!sourceRoot.startsWith(`${downloads}${path.sep}`)) throw new Error("Refusing to package a system Python");
await fs.cp(sourceRoot, path.join(staging, "python"), { recursive: true, verbatimSymlinks: true });
const python = path.join(staging, "python", ...(process.platform === "win32" ? ["python.exe"] : ["bin", "python3"]));
// Install wheels into a relocatable directory; never copy an editable project venv.
const requirements = (await fs.readFile(path.join(repo, "backend", "requirements.txt"), "utf8"))
  .split(/\r?\n/).filter((line) => !line.startsWith("-e ")).join("\n");
const requirementsPath = path.join(staging, "requirements.txt");
await fs.writeFile(requirementsPath, requirements);
const site = path.join(staging, "site-packages");
run(uv, ["pip", "install", "--python", python, "--target", site, "-r", requirementsPath,
  path.join(repo, "packages", "candlescope-plugin-sdk"), path.join(repo, "packages", "candlescope-backtest-sdk")]);
run(python, ["-c", "import fastapi, uvicorn, numpy, pandas, orjson, ccxt, exchange_calendars, candlescope_plugin_sdk, candlescope_backtest_sdk"], {
  env: { ...process.env, PYTHONPATH: site, PYTHONNOUSERSITE: "1" },
});
const installed = spawnSync(uv, ["pip", "freeze", "--python", python, "--path", site], { encoding: "utf8" });
if (installed.status !== 0) throw new Error(installed.stderr);
await fs.writeFile(path.join(staging, "installed-requirements.txt"), installed.stdout);
await fs.writeFile(path.join(staging, "manifest.json"), JSON.stringify({
  platform: process.platform, arch: process.arch, builtAt: new Date().toISOString(),
  python: path.basename(sourceRoot),
}, null, 2));
const destination = path.join(cache, "runtime");
try { await fs.rename(destination, path.join(cache, `previous-${Date.now()}`)); }
catch (error) { if (error.code !== "ENOENT") throw error; }
await fs.rename(staging, destination);
console.log(`Prepared standalone backend runtime: ${destination}`);
