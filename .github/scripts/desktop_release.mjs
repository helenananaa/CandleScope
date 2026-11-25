// Helpers for .github/workflows/desktop-release.yml. No dependencies.
//   check     --tag <name or empty>                 version and release note checks
//   assemble  --input <dir> --output <dir> --version <v> --commit <sha> [--tag <name>] [--dry-run]
import { createHash } from "node:crypto";
import { appendFileSync, copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

/** The packages a release must contain, by build manifest platform and arch. */
export const EXPECTED_PACKAGES = [
  { platform: "darwin", arch: "arm64", label: "macOS, Apple silicon (M1 and later)", files: (v) => [`CandleScope-${v}-macos-arm64.dmg`, `CandleScope-${v}-macos-arm64.zip`] },
  { platform: "darwin", arch: "x64", label: "macOS, Intel", files: (v) => [`CandleScope-${v}-macos-x64.dmg`, `CandleScope-${v}-macos-x64.zip`] },
  { platform: "win32", arch: "x64", label: "Windows 10 and 11 (x64)", files: (v) => [`CandleScope-${v}-windows-x64-setup.exe`] },
];

export function readVersions(root = repoRoot) {
  const pkg = JSON.parse(readFileSync(path.join(root, "frontend", "package.json"), "utf8")).version;
  const backend = readFileSync(path.join(root, "backend", "app", "core", "version.py"), "utf8")
    .match(/^APP_VERSION\s*=\s*["']([^"']+)["']/m)?.[1];
  return { pkg, backend };
}

/** The section of RELEASE_NOTES.md under `## <version>` (also `## v1.0.0 (date)`), or null. */
export function releaseNotesSection(markdown, heading) {
  const escaped = heading.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const lines = markdown.split(/\r?\n/);
  const start = lines.findIndex((line) => new RegExp(`^## v?${escaped}(?=\\s|$)`, "i").test(line));
  if (start < 0) return null;
  const end = lines.findIndex((line, index) => index > start && /^## /.test(line));
  return lines.slice(start + 1, end < 0 ? undefined : end).join("\n").trim();
}

/** Point repository-relative links at the tagged source, since a release body has no base path. */
export function absoluteLinks(markdown, repository, ref) {
  return markdown.replace(/\]\((?!https?:|mailto:|#)([^)\s]+)\)/g, (_, target) =>
    `](https://github.com/${repository}/blob/${ref}/${path.posix.normalize(target).replace(/^(\.\.\/)+/, "")})`);
}

export function checkRelease({ tag, versions, notes }) {
  const errors = [];
  if (!versions.pkg || versions.pkg !== versions.backend) {
    errors.push(`frontend/package.json version ${versions.pkg} must match backend APP_VERSION ${versions.backend}`);
  }
  if (!/^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$/.test(versions.pkg ?? "")) errors.push(`Version ${versions.pkg} is not semver`);
  if (tag) {
    if (tag !== `v${versions.pkg}`) errors.push(`Tag ${tag} must be v${versions.pkg}, the version in frontend/package.json`);
    if (!releaseNotesSection(notes, versions.pkg)) errors.push(`RELEASE_NOTES.md needs a "## ${versions.pkg}" section`);
  }
  return { errors, version: versions.pkg, prerelease: (versions.pkg ?? "").includes("-") };
}

const sha256 = (file) => createHash("sha256").update(readFileSync(file)).digest("hex");

/** Verify every CI artifact against its own checksums and commit, then gather one release folder. */
export function assembleRelease({ input, output, version, commit }) {
  const builds = readdirSync(input, { withFileTypes: true }).filter((entry) => entry.isDirectory())
    .map((entry) => path.join(input, entry.name));
  const manifests = [];
  const sums = [];
  mkdirSync(output, { recursive: true });
  for (const expected of EXPECTED_PACKAGES) {
    const matches = builds.filter((dir) => {
      const file = path.join(dir, "build-manifest.json");
      if (!existsSync(file)) return false;
      const manifest = JSON.parse(readFileSync(file, "utf8"));
      return manifest.platform === expected.platform && manifest.arch === expected.arch;
    });
    if (matches.length !== 1) throw new Error(`Expected one ${expected.platform}-${expected.arch} build, found ${matches.length}`);
    const dir = matches[0];
    const manifest = JSON.parse(readFileSync(path.join(dir, "build-manifest.json"), "utf8"));
    if (manifest.commit !== commit) throw new Error(`${expected.platform}-${expected.arch} was built from ${manifest.commit}, not ${commit}`);
    const listed = new Map(readFileSync(path.join(dir, "SHA256SUMS"), "utf8").trim().split("\n")
      .map((line) => line.match(/^([0-9a-f]{64}) {2}(.+)$/)).filter(Boolean).map((m) => [m[2], m[1]]));
    const names = expected.files(version);
    if (listed.size !== names.length || names.some((name) => !listed.has(name))) {
      throw new Error(`${expected.platform}-${expected.arch} must contain exactly ${names.join(", ")}; SHA256SUMS lists ${[...listed.keys()].join(", ")}`);
    }
    for (const name of names) {
      const file = path.join(dir, name);
      if (!existsSync(file)) throw new Error(`Missing ${name}`);
      const digest = sha256(file);
      if (digest !== listed.get(name)) throw new Error(`Checksum mismatch for ${name}`);
      copyFileSync(file, path.join(output, name));
      sums.push(`${digest}  ${name}`);
    }
    manifests.push(manifest);
  }
  writeFileSync(path.join(output, "SHA256SUMS"), sums.sort((a, b) => a.slice(66).localeCompare(b.slice(66))).join("\n") + "\n");
  writeFileSync(path.join(output, "build-manifests.json"), JSON.stringify(manifests, null, 2) + "\n");
  return { files: sums.map((line) => line.slice(66)) };
}

export function releaseBody({ version, notes, repository, ref, dryRun }) {
  const section = releaseNotesSection(notes, version) ?? (dryRun ? releaseNotesSection(notes, "Unreleased") : null);
  const rows = EXPECTED_PACKAGES.map((item) => `| ${item.label} | ${item.files(version).map((name) => `\`${name}\``).join(" or ")} |`);
  return [
    ...(dryRun ? ["> Dry run: built from an untagged commit. Nothing was published.", ""] : []),
    "## Downloads",
    "",
    "| System | File |",
    "|---|---|",
    ...rows,
    "",
    "Check a download against `SHA256SUMS`. `build-manifests.json` names the commit and CI run each package came from.",
    "",
    "### First launch",
    "",
    "These packages are not signed with a paid certificate, so the system asks once before the first launch.",
    "",
    "- **macOS:** open the DMG and drag CandleScope to Applications. Open it; when macOS says it cannot verify the app, go to **System Settings → Privacy & Security** and choose **Open Anyway**.",
    "- **Windows:** run the setup file. If SmartScreen says *Windows protected your PC*, choose **More info → Run anyway**. Uninstalling keeps your data in `%APPDATA%\\CandleScope Replay`.",
    "",
    "首次打开：安装包没有使用付费证书签名。macOS 被拦截后到 **系统设置 → 隐私与安全性** 选择 **仍要打开**；Windows 在 SmartScreen 提示中选择 **更多信息 → 仍要运行**。",
    "",
    "## What's new",
    "",
    section ? absoluteLinks(section, repository, ref) : "See RELEASE_NOTES.md.",
    "",
  ].join("\n");
}

function args(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    if (!argv[i].startsWith("--")) continue;
    const key = argv[i].slice(2);
    out[key] = argv[i + 1] === undefined || argv[i + 1].startsWith("--") ? true : argv[(i += 1)];
  }
  return out;
}

function output(values) {
  if (!process.env.GITHUB_OUTPUT) return;
  for (const [key, value] of Object.entries(values)) appendFileSync(process.env.GITHUB_OUTPUT, `${key}=${value}\n`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [command, ...rest] = process.argv.slice(2);
  const options = args(rest);
  const notes = readFileSync(path.join(repoRoot, "RELEASE_NOTES.md"), "utf8");
  if (command === "check") {
    const result = checkRelease({ tag: typeof options.tag === "string" ? options.tag : "", versions: readVersions(), notes });
    if (result.errors.length) {
      for (const error of result.errors) console.error(`::error::${error}`);
      process.exit(1);
    }
    console.log(`Version ${result.version}${result.prerelease ? " (prerelease)" : ""}`);
    output({ version: result.version, prerelease: String(result.prerelease) });
  } else if (command === "assemble") {
    const { files } = assembleRelease({ input: options.input, output: options.output, version: options.version, commit: options.commit });
    const body = releaseBody({
      version: options.version, notes, dryRun: options["dry-run"] === true,
      repository: process.env.GITHUB_REPOSITORY ?? "helenananaa/CandleScope",
      ref: typeof options.tag === "string" && options.tag ? options.tag : options.commit,
    });
    writeFileSync(path.join(options.output, "release-notes.md"), body);
    console.log(`Assembled ${files.length} packages:\n${files.join("\n")}`);
  } else {
    console.error("Usage: desktop_release.mjs check|assemble …");
    process.exit(2);
  }
}
