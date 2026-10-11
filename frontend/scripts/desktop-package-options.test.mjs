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
