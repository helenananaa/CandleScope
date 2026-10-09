import { createHash } from "node:crypto";
import { readFile, readdir, writeFile } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import path from "node:path";

const directory = path.resolve("desktop-dist");
const files = (await readdir(directory)).filter(name => /\.(dmg|zip)$/.test(name)).sort();
if (files.length !== 2) throw new Error("Expected one DMG and one ZIP for this architecture");
const artifacts = await Promise.all(files.map(async name => {
  const bytes = await readFile(path.join(directory, name));
  return { name, size: bytes.length, sha256: createHash("sha256").update(bytes).digest("hex") };
}));
await writeFile(path.join(directory, "SHA256SUMS"), artifacts.map(item => `${item.sha256}  ${item.name}\n`).join(""));
await writeFile(path.join(directory, "build-manifest.json"), JSON.stringify({
  schemaVersion: 1,
  commit: execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim(),
  platform: process.platform, arch: process.arch,
  signature: "ad-hoc", notarized: false,
  workflowRun: process.env.GITHUB_RUN_ID || null,
  artifacts,
}, null, 2) + "\n");
