import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { absoluteLinks, assembleRelease, checkRelease, EXPECTED_PACKAGES, releaseBody, releaseNotesSection } from "./desktop_release.mjs";

const NOTES = `# Release notes

## 1.0.0 (2026-11-30)

### First public release

See [the macOS guide](docs/MACOS_DESKTOP.md) and [below](#going-back).

## Unreleased draft

Not this one.
`;

test("a release notes section is found by version, with or without a v or a date", () => {
  assert.match(releaseNotesSection(NOTES, "1.0.0"), /^### First public release/);
  assert.match(releaseNotesSection("## v1.0.0\n\nText\n", "1.0.0"), /^Text$/);
  assert.equal(releaseNotesSection(NOTES, "1.0"), null);
  assert.equal(releaseNotesSection(NOTES, "1.0.0-rc.1"), null);
  assert.equal(releaseNotesSection(NOTES, "Unreleased"), "Not this one.");
});

test("a tag must equal v plus the app version, which both version files share", () => {
  const ok = checkRelease({ tag: "v1.0.0", versions: { pkg: "1.0.0", backend: "1.0.0" }, notes: NOTES });
  assert.deepEqual(ok, { errors: [], version: "1.0.0", prerelease: false });
  assert.equal(checkRelease({ tag: "v1.0.1", versions: { pkg: "1.0.0", backend: "1.0.0" }, notes: NOTES }).errors.length, 1);
  assert.equal(checkRelease({ tag: "", versions: { pkg: "1.0.0", backend: "0.3.0" }, notes: NOTES }).errors.length, 1);
  // Without a tag (a dry run) the release notes section is not required yet.
  assert.deepEqual(checkRelease({ tag: "", versions: { pkg: "0.3.0", backend: "0.3.0" }, notes: NOTES }).errors, []);
  const missingNotes = checkRelease({ tag: "v0.3.0", versions: { pkg: "0.3.0", backend: "0.3.0" }, notes: NOTES });
  assert.match(missingNotes.errors.join(), /RELEASE_NOTES.md needs a "## 0.3.0" section/);
  assert.equal(checkRelease({ tag: "v1.1.0-rc.1", versions: { pkg: "1.1.0-rc.1", backend: "1.1.0-rc.1" }, notes: "## 1.1.0-rc.1\n\nx" }).prerelease, true);
});

test("repository links point at the tagged source; anchors and web links stay", () => {
  assert.equal(
    absoluteLinks("[a](docs/A.md#x) [b](#here) [c](https://example.com/y)", "owner/repo", "v1.0.0"),
    "[a](https://github.com/owner/repo/blob/v1.0.0/docs/A.md#x) [b](#here) [c](https://example.com/y)",
  );
});

function fakeBuilds(root, version, commit, change = () => {}) {
  for (const item of EXPECTED_PACKAGES) {
    const dir = path.join(root, `CandleScope-${item.platform}-${item.arch}-${commit}`);
    mkdirSync(dir, { recursive: true });
    const lines = item.files(version).map((name) => {
      const bytes = Buffer.from(`${name} bytes`);
      writeFileSync(path.join(dir, name), bytes);
      return `${createHash("sha256").update(bytes).digest("hex")}  ${name}\n`;
    });
    const manifest = { schemaVersion: 1, commit, platform: item.platform, arch: item.arch, artifacts: [] };
    change(item, dir, manifest, lines);
    writeFileSync(path.join(dir, "SHA256SUMS"), lines.join(""));
    writeFileSync(path.join(dir, "build-manifest.json"), JSON.stringify(manifest));
  }
}

test("assembling verifies each build and writes one checksum list", () => {
  const root = mkdtempSync(path.join(tmpdir(), "desktop-release-"));
  fakeBuilds(path.join(root, "in"), "1.0.0", "abc");
  const { files } = assembleRelease({ input: path.join(root, "in"), output: path.join(root, "out"), version: "1.0.0", commit: "abc" });
  assert.equal(files.length, 6);
  const sums = readFileSync(path.join(root, "out", "SHA256SUMS"), "utf8").trim().split("\n");
  assert.deepEqual(sums.map((line) => line.slice(66)), [
    "CandleScope-1.0.0-macos-arm64.dmg", "CandleScope-1.0.0-macos-arm64.zip",
    "CandleScope-1.0.0-macos-x64.dmg", "CandleScope-1.0.0-macos-x64.zip",
    "CandleScope-1.0.0-windows-x64-setup.exe", "CandleScope-1.0.0-windows-x64.zip",
  ]);
  assert.equal(JSON.parse(readFileSync(path.join(root, "out", "build-manifests.json"), "utf8")).length, 3);
});

test("assembling refuses a build from another commit, a changed file or a missing platform", () => {
  const cases = [
    [(item, dir, manifest) => { if (item.platform === "win32") manifest.commit = "other"; }, /built from other, not abc/],
    [(item, dir) => { if (item.arch === "x64" && item.platform === "darwin") writeFileSync(path.join(dir, "CandleScope-1.0.0-macos-x64.zip"), "changed"); }, /Checksum mismatch/],
    [(item, dir, manifest) => { if (item.platform === "win32") manifest.platform = "linux"; }, /Expected one win32-x64 build, found 0/],
    [(item, dir, manifest, lines) => { if (item.platform === "win32") lines.push(`${"0".repeat(64)}  extra.exe\n`); }, /must contain exactly/],
    // A Windows build that recorded only its installer is incomplete.
    [(item, dir, manifest, lines) => { if (item.platform === "win32") lines.pop(); }, /must contain exactly/],
  ];
  for (const [change, error] of cases) {
    const root = mkdtempSync(path.join(tmpdir(), "desktop-release-"));
    fakeBuilds(path.join(root, "in"), "1.0.0", "abc", change);
    assert.throws(() => assembleRelease({ input: path.join(root, "in"), output: path.join(root, "out"), version: "1.0.0", commit: "abc" }), error);
  }
});

test("the release body lists every package, the first-launch steps and the version's notes", () => {
  const body = releaseBody({ version: "1.0.0", notes: NOTES, repository: "owner/repo", ref: "v1.0.0", dryRun: false });
  for (const item of EXPECTED_PACKAGES) for (const name of item.files("1.0.0")) assert.ok(body.includes(name), name);
  assert.match(body, /Open Anyway/);
  assert.match(body, /More info → Run anyway/);
  assert.match(body, /extract the ZIP to a folder and run `CandleScope\.exe`/);
  assert.match(body, /\| Windows 10 and 11 \(x64\) \| `CandleScope-1\.0\.0-windows-x64-setup\.exe` or `CandleScope-1\.0\.0-windows-x64\.zip` \|/);
  assert.match(body, /### First public release/);
  assert.match(body, /blob\/v1\.0\.0\/docs\/MACOS_DESKTOP\.md/);
  assert.doesNotMatch(body, /Dry run/);
  const dry = releaseBody({ version: "0.3.0", notes: NOTES, repository: "owner/repo", ref: "abc", dryRun: true });
  assert.match(dry, /^> Dry run/);
  assert.match(dry, /Not this one\./);
});
