import path from "node:path";
import { existsSync, realpathSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
// Use the same physical root for Vite inputs and its working directory on
// Windows mapped drives/junctions, otherwise emitted HTML paths escape root.
const frontend = realpathSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), ".."));
function run(script, args = [], env = process.env) {
  const result = spawnSync(process.execPath, [script, ...args], { cwd: frontend, stdio: "inherit", env });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
const backendVersion = readFileSync(path.join(frontend, "../backend/app/core/version.py"), "utf8")
  .match(/^APP_VERSION\s*=\s*["']([^"']+)["']/m)?.[1];
const packageVersion = JSON.parse(readFileSync(path.join(frontend, "package.json"), "utf8")).version;
if (!backendVersion || packageVersion !== backendVersion) {
  throw new Error(`Desktop package version ${packageVersion} must match backend APP_VERSION ${backendVersion}`);
}
run("scripts/prepare-desktop-runtime.mjs");
run("node_modules/vite/bin/vite.js", ["build"], { ...process.env, VITE_DESKTOP_BUILD: "1" });
// npm installations with lifecycle scripts disabled need builder's verified download.
const localElectron = path.join(frontend, "node_modules", "electron", "dist");
run("node_modules/electron-builder/cli.js", ["--dir",
  ...(existsSync(localElectron) ? ["-c.electronDist=node_modules/electron/dist"] : []),
  ...process.argv.slice(2)]);
