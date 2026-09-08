import assert from "node:assert/strict";
import test from "node:test";
import path from "node:path";
import { bundledPythonPath, resolvePythonCommand } from "./python-runtime.mjs";

test("packaged runtime uses its own interpreter without consulting PATH", () => {
  assert.equal(resolvePythonCommand({ runtimeRoot: "/app", packaged: true, exists: () => true }), bundledPythonPath("/app"));
});
test("explicit user Python override remains supported", () => {
  assert.equal(resolvePythonCommand({ runtimeRoot: "/app", packaged: true, override: "/custom/python", exists: () => false }), "/custom/python");
});
test("missing packaged runtime fails clearly instead of selecting an unrelated system Python", () => {
  assert.throws(() => resolvePythonCommand({ runtimeRoot: "/app", packaged: true, exists: () => false }), /runtime is missing/);
  assert.equal(resolvePythonCommand({ runtimeRoot: "/repo", packaged: false, exists: () => false }), "python");
});
test("Windows interpreter path has no POSIX bin segment", () => {
  assert.equal(bundledPythonPath("/app", "win32"), path.join("/app", "python-runtime", "python", "python.exe"));
});
