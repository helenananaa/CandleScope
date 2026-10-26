import { spawnSync } from "node:child_process";
import { build } from "esbuild";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const controlPackage = path.join(frontend, "../packages/candlescope-control");
// Build entry points live outside frontend, so install their own locked dependencies.
const installed = spawnSync(process.platform === "win32" ? "npm.cmd" : "npm",
  ["ci", "--ignore-scripts", "--omit=dev", "--no-audit", "--no-fund"],
  { cwd: controlPackage, stdio: "inherit", shell: process.platform === "win32" });
if (installed.error) throw installed.error;
if (installed.status !== 0) throw new Error("Could not install the locked control adapter dependencies");
const output = path.join(frontend, ".desktop-runtime/control");
await mkdir(output, { recursive: true });
const result = await build({ entryPoints: [path.join(frontend, "../packages/candlescope-control/cli.mjs")],
  outfile: path.join(output, "cli.mjs"), bundle: true, platform: "node", format: "esm", target: "node22", metafile: true,
  banner: { js: 'import { createRequire as bundledCreateRequire } from "node:module"; const require = bundledCreateRequire(import.meta.url);' } });
const remaining = Object.values(result.metafile.outputs).flatMap((entry) => entry.imports).filter((entry) => entry.external && !entry.path.startsWith("node:"));
if (remaining.length) throw new Error(`Control adapter has unbundled dependencies: ${JSON.stringify(remaining)}`);
const dependencyRoots = new Set();
for (const filename of Object.keys(result.metafile.inputs)) {
  if (!filename.includes("node_modules")) continue;
  let current = path.dirname(path.resolve(filename));
  while (path.dirname(current) !== current) {
    if (existsSync(path.join(current, "package.json"))) {
      const metadata = JSON.parse(await readFile(path.join(current, "package.json"), "utf8"));
      if (metadata.name) { dependencyRoots.add(current); break; }
    }
    current = path.dirname(current);
  }
}
const notices = [];
for (const dependency of [...dependencyRoots].sort()) {
  const metadata = JSON.parse(await readFile(path.join(dependency, "package.json"), "utf8"));
  const sections = [];
  for (const name of ["LICENSE", "LICENSE.md", "LICENSE.txt", "NOTICE", "NOTICE.md", "NOTICE.txt"]) {
    if (existsSync(path.join(dependency, name))) sections.push(`${name}\n${await readFile(path.join(dependency, name), "utf8")}`);
  }
  if (!sections.length) throw new Error(`Missing bundled dependency license: ${metadata.name}`);
  notices.push(`${metadata.name} ${metadata.version}\n${sections.join("\n\n")}`);
}
await writeFile(path.join(output, "THIRD-PARTY-NOTICES.txt"), notices.join("\n\n========================================\n\n"));
await writeFile(path.join(output, "manifest.json"), JSON.stringify({ schema: "candlescope.control-bundle/1",
  sha256: createHash("sha256").update(await readFile(path.join(output, "cli.mjs"))).digest("hex"),
  runtime: "Electron ELECTRON_RUN_AS_NODE", externalDependencies: [] }, null, 2));
console.log(`Prepared standalone control adapter: ${output}`);
