import path from "node:path";
import { existsSync, realpathSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { desktopBuilderArguments } from "./desktop-package-options.mjs";
// Use the same physical root for Vite inputs and its working directory on
// Windows mapped drives/junctions, otherwise emitted HTML paths escape root.
const frontend = realpathSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), ".."));
function run(script, args = [], env = process.env) {
  const result = spawnSync(process.execPath, [script, ...args], { cwd: frontend, stdio: "inherit", env });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
run("scripts/prepare-desktop-runtime.mjs");
run("node_modules/vite/bin/vite.js", ["build"], { ...process.env, VITE_DESKTOP_BUILD: "1" });
// npm installations with lifecycle scripts disabled need builder's verified download.
const localElectron = path.join(frontend, "node_modules", "electron", "dist");
run("node_modules/electron-builder/cli.js", desktopBuilderArguments(process.argv.slice(2), existsSync(localElectron)));
