import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import test from "node:test";

async function prepareFixture(t, failure = "") {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "candlescope-runtime-pipeline-"));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const frontend = path.join(root, "frontend"), scripts = path.join(frontend, "scripts");
  const cache = path.join(frontend, ".desktop-runtime");
  await fs.mkdir(scripts, { recursive: true });
  await fs.mkdir(path.join(root, "backend"));
  for (const name of ["requirements.txt", "requirements-parquet.txt"]) {
    await fs.writeFile(path.join(root, "backend", name), "fixture==1\n");
  }
  for (const name of ["runtime", "previous-100", "previous-200", "downloads", "control", "plugin-build", "staging-other-build"]) {
    await fs.mkdir(path.join(cache, name), { recursive: true });
    await fs.writeFile(path.join(cache, name, "marker"), name);
  }
  for (const name of ["prepare-desktop-runtime.mjs", "desktop-runtime-cache.mjs"]) {
    await fs.copyFile(new URL(name, import.meta.url), path.join(scripts, name));
  }
  const preload = path.join(root, "native-fixture.mjs");
  // Run the real entry point and filesystem lifecycle. Only tool subprocesses
  // are fixtures, so this never downloads Python or builds upstream engines.
  await fs.writeFile(preload, `
    import assert from "node:assert/strict";
    import cp from "node:child_process";
    import fs from "node:fs";
    import path from "node:path";
    import { syncBuiltinESMExports } from "node:module";
    const root = process.env.CANDLESCOPE_TEST_ROOT;
    const cache = path.join(root, "frontend", ".desktop-runtime");
    const pythonRoot = path.join(cache, "downloads", "cpython-fixture");
    const executable = process.platform === "win32" ? path.join(pythonRoot, "python.exe") : path.join(pythonRoot, "bin", "python3");
    cp.spawnSync = (command, args) => {
      let phase, stdout = "";
      if (args[0] === "python" && args[1] === "install") {
        phase = "download";
        fs.mkdirSync(path.dirname(executable), { recursive: true });
        fs.writeFileSync(executable, "fixture Python");
      } else if (args[0] === "python" && args[1] === "find") {
        phase = "find"; stdout = executable + "\\n";
      } else if (args[0] === "pip" && args[1] === "install") {
        phase = "dependencies";
        const site = args[args.indexOf("--target") + 1];
        fs.mkdirSync(site, { recursive: true });
        fs.writeFileSync(path.join(site, "installed"), "dependency fixture");
      } else if (args[0] === "-c") {
        phase = "imports";
      } else if (args[0] === "pip" && args[1] === "freeze") {
        phase = "freeze"; stdout = "fixture==1\\n";
      } else if (args[0].endsWith("prepare-desktop-plugins.py")) {
        phase = "plugins";
        assert.equal(fs.readFileSync(path.join(cache, "runtime", "marker"), "utf8"), "runtime");
        assert.equal(args[args.indexOf("--cache") + 1], path.join(cache, "plugin-build"));
        const output = args[args.indexOf("--output") + 1];
        fs.mkdirSync(output, { recursive: true });
        fs.writeFileSync(path.join(output, "bundle.cspkg"), "built plugin");
      } else { throw new Error("Unexpected fixture tool invocation"); }
      fs.appendFileSync(path.join(root, "calls.jsonl"), JSON.stringify({ phase, command, args }) + "\\n");
      return { status: phase === process.env.CANDLESCOPE_TEST_FAILURE ? 27 : 0, stdout, stderr: "" };
    };
    syncBuiltinESMExports();
  `);
  const result = spawnSync(process.execPath, ["--import", pathToFileURL(preload).href,
    path.join(scripts, "prepare-desktop-runtime.mjs")], {
    env: { ...process.env, CANDLESCOPE_UV: "fixture-uv", CANDLESCOPE_TEST_ROOT: root, CANDLESCOPE_TEST_FAILURE: failure },
    encoding: "utf8", windowsHide: true, timeout: 10_000,
  });
  const calls = (await fs.readFile(path.join(root, "calls.jsonl"), "utf8")).trim().split("\n").map(line => JSON.parse(line));
  return { cache, result, calls };
}

test("the preparation entry point promotes installed dependencies and built plugins together", async t => {
  const { cache, result, calls } = await prepareFixture(t);
  assert.equal(result.status, 0, result.stdout + result.stderr);
  assert.ok(calls.some(call => call.phase === "plugins"));
  assert.equal(await fs.readFile(path.join(cache, "runtime", "plugins", "bundle.cspkg"), "utf8"), "built plugin");
  assert.equal(await fs.readFile(path.join(cache, "runtime", "site-packages", "installed"), "utf8"), "dependency fixture");
  const backups = (await fs.readdir(cache)).filter(name => name.startsWith("previous-"));
  assert.equal(backups.length, 1);
  assert.equal(await fs.readFile(path.join(cache, backups[0], "marker"), "utf8"), "runtime");
  for (const name of ["downloads", "control", "plugin-build", "staging-other-build"]) {
    assert.equal(await fs.readFile(path.join(cache, name, "marker"), "utf8"), name);
  }
});

for (const phase of ["dependencies", "plugins"]) {
  test(`the preparation entry point preserves the active runtime when ${phase} fail`, async t => {
    const { cache, result, calls } = await prepareFixture(t, phase);
    assert.equal(result.status, 1, result.stdout + result.stderr);
    assert.match(result.stderr, /exited with 27/);
    assert.equal(calls.at(-1).phase, phase);
    assert.equal(await fs.readFile(path.join(cache, "runtime", "marker"), "utf8"), "runtime");
    for (const name of ["previous-100", "previous-200", "downloads", "control", "plugin-build", "staging-other-build"]) {
      assert.equal(await fs.readFile(path.join(cache, name, "marker"), "utf8"), name);
    }
    assert.deepEqual((await fs.readdir(cache)).filter(name => name.startsWith("staging-")), ["staging-other-build"]);
  });
}
