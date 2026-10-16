import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

const runner = fileURLToPath(new URL("./run-frontend-tests.mjs", import.meta.url));
const performanceTest = "src/features/drawings/core/__tests__/drawingCommandPerformance.test.ts";

function fixture(context, sources) {
  const cwd = fs.mkdtempSync(path.join(os.tmpdir(), "candlescope-frontend-runner-"));
  context.after(() => fs.rmSync(cwd, { recursive: true, force: true }));
  for (const [name, source] of Object.entries(sources)) {
    const file = path.join(cwd, name);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, source);
  }
  const env = { ...process.env };
  delete env.NODE_TEST_CONTEXT;
  return {
    cwd,
    run: (...args) => spawnSync(process.execPath, [runner, ...args], { cwd, env, encoding: "utf8", timeout: 30_000 }),
  };
}

test("performance gate waits for every functional test and overlapping globs run each file once", (context) => {
  const source = (name) => `
    import fs from 'node:fs';
    import test from 'node:test';
    process.on('exit', () => fs.writeFileSync('${name}.exited', '1'));
    test('${name}', async () => {
      await new Promise(resolve => setTimeout(resolve, 75));
      fs.appendFileSync('${name}.done', '1');
    });
  `;
  const suite = fixture(context, {
    "src/colocated.test.ts": source("colocated"),
    "src/nested/component.test.tsx": source("nested"),
    [performanceTest]: `
      import assert from 'node:assert/strict';
      import fs from 'node:fs';
      import test from 'node:test';
      test('performance gate', () => {
        assert.equal(fs.readFileSync('colocated.done', 'utf8'), '1');
        assert.equal(fs.readFileSync('nested.done', 'utf8'), '1');
        assert.equal(fs.readFileSync('colocated.exited', 'utf8'), '1');
        assert.equal(fs.readFileSync('nested.exited', 'utf8'), '1');
        fs.writeFileSync('performance.done', '1');
      });
    `,
  });
  const result = suite.run("src/**/*.test.{ts,tsx}", "src/**/*.test.ts");
  assert.equal(result.status, 0, result.stderr + result.stdout);
  assert.equal(fs.readFileSync(path.join(suite.cwd, "performance.done"), "utf8"), "1");
  assert.match(result.stdout, /functional: 2 files, concurrency=4/);
  assert.match(result.stdout, /isolated performance gate: 1 files, concurrency=1/);
});

test("functional failures stay nonzero while the independent performance gate still runs", (context) => {
  const suite = fixture(context, {
    "src/failure.test.ts": "import test from 'node:test'; test('functional failure', () => { throw Error('expected functional failure'); });",
    [performanceTest]: "import fs from 'node:fs'; import test from 'node:test'; test('gate ran', () => { fs.writeFileSync('performance.done', '1'); });",
  });
  const result = suite.run();
  assert.equal(result.status, 1, result.stderr + result.stdout);
  assert.match(result.stdout, /expected functional failure/);
  assert.ok(fs.existsSync(path.join(suite.cwd, "performance.done")));
});

test("a failing isolated performance gate fails the complete command", (context) => {
  const suite = fixture(context, {
    "src/pass.test.ts": "import test from 'node:test'; test('functional pass', () => {});",
    [performanceTest]: "import test from 'node:test'; test('gate failure', () => { throw Error('expected performance failure'); });",
  });
  const result = suite.run();
  assert.equal(result.status, 1, result.stderr + result.stdout);
  assert.match(result.stdout, /expected performance failure/);
});

test("empty selections and invalid worker counts cannot report success", (context) => {
  const suite = fixture(context, {});
  for (const args of [["missing/**/*.test.ts"], ["--workers", "0"], ["--workers"]]) {
    const result = suite.run(...args);
    assert.equal(result.status, 2);
  }
});
