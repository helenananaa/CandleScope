import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { desktopBuilderArguments } from "./desktop-package-options.mjs";

test("existing desktop packaging remains unpacked", () => {
  assert.deepEqual(desktopBuilderArguments(), ["--dir"]);
  assert.deepEqual(desktopBuilderArguments(["--mac", "--arm64"], true), [
    "--dir", "-c.electronDist=node_modules/electron/dist", "--mac", "--arm64",
  ]);
});

test("macOS distributables preserve explicit architecture and never publish", () => {
  const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url)));
  const args = pkg.scripts["desktop:package:mac"].split(" ").slice(2);
  assert.deepEqual(desktopBuilderArguments([...args, "--arm64"]), [
    "--mac", "dmg", "zip", "--publish", "never", "--arm64",
  ]);
  assert.deepEqual(pkg.build.mac.target, ["dmg", "zip"]);
  assert.equal(pkg.build.mac.identity, "-");
  assert.equal(pkg.build.mac.hardenedRuntime, false);
  assert.equal(pkg.build.mac.notarize, false);
  assert.ok(pkg.build.mac.artifactName.includes("${arch}"));
});

test("Windows ships a per-user installer and a ZIP, never publishes, and keeps user data on uninstall", () => {
  const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url)));
  const args = pkg.scripts["desktop:package:win"].split(" ").slice(2);
  assert.deepEqual(desktopBuilderArguments([...args, "--x64"]), [
    "--win", "nsis", "zip", "--publish", "never", "--x64",
  ]);
  assert.deepEqual(pkg.build.win.target, ["nsis", "zip"]);
  assert.equal(pkg.build.nsis.oneClick, false);
  assert.equal(pkg.build.nsis.perMachine, false);
  assert.equal(pkg.build.nsis.deleteAppDataOnUninstall, false);
  // The release workflow and record-desktop-artifacts.mjs find both files by these names:
  // the installer keeps its -setup suffix, the ZIP takes the platform name.
  assert.match(pkg.build.nsis.artifactName, /-windows-\$\{arch\}-setup\.\$\{ext\}$/);
  assert.match(pkg.build.win.artifactName, /-windows-\$\{arch\}\.\$\{ext\}$/);
});
