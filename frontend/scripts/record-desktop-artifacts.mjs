import { createHash } from "node:crypto";
import { readFile, readdir, writeFile } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import path from "node:path";

// macOS ships a DMG and a ZIP per architecture; Windows ships one installer.
const expected = {
  darwin: { pattern: /\.(dmg|zip)$/, count: 2, signature: "ad-hoc", describe: "one DMG and one ZIP" },
  win32: { pattern: /-setup\.exe$/, count: 1, signature: "unsigned", describe: "one setup EXE" },
}[process.platform];
if (!expected) throw new Error(`No desktop distributables are defined for ${process.platform}`);
const directory = path.resolve("desktop-dist");
const files = (await readdir(directory)).filter(name => expected.pattern.test(name)).sort();
if (files.length !== expected.count) throw new Error(`Expected ${expected.describe} for this architecture, found: ${files.join(", ") || "none"}`);
const artifacts = await Promise.all(files.map(async name => {
  const bytes = await readFile(path.join(directory, name));
  return { name, size: bytes.length, sha256: createHash("sha256").update(bytes).digest("hex") };
}));
await writeFile(path.join(directory, "SHA256SUMS"), artifacts.map(item => `${item.sha256}  ${item.name}\n`).join(""));
await writeFile(path.join(directory, "build-manifest.json"), JSON.stringify({
  schemaVersion: 1,
  commit: execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim(),
  platform: process.platform, arch: process.arch,
  signature: expected.signature, notarized: false,
  workflowRun: process.env.GITHUB_RUN_ID || null,
  artifacts,
}, null, 2) + "\n");
