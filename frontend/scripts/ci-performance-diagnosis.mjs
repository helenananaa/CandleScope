import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";

const target = "src/features/drawings/core/__tests__/drawingCommandPerformance.test.ts";
const original = fs.readFileSync(target, "utf8");
const output = path.resolve("../output/ci-performance-diagnosis");
fs.mkdirSync(output, { recursive: true });
const report = {
  node: process.version,
  arch: process.arch,
  parallelism: os.availableParallelism(),
  cpus: os.cpus().map(({ model, speed }) => ({ model, speed })),
  memory: os.totalmem(),
  runs: [],
};

function run(label, args) {
  const logPath = path.join(output, `${label}.log`);
  const log = fs.openSync(logPath, "w");
  let result;
  try {
    result = spawnSync(process.execPath, args, {
      stdio: ["ignore", log, log],
      timeout: 600_000,
      env: process.env,
    });
  } finally {
    fs.closeSync(log);
  }
  const text = fs.readFileSync(logPath, "utf8");
  const diagnostics = text.split("\n").filter((line) => /style\/move\/reorder attempt|CI_SAMPLE_METRICS|ℹ (tests|pass|fail|duration_ms)|AssertionError/.test(line));
  const entry = { label, status: result.status, signal: result.signal, error: result.error?.message, diagnostics };
  report.runs.push(entry);
  fs.writeFileSync(path.join(output, "report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(entry));
}

const nodeTest = ["--import", "./scripts/monaco-esm-loader.mjs", "--import", "tsx", "--test"];
for (let trial = 1; trial <= 3; trial++) {
  run(`original-isolated-${trial}`, [...nodeTest, "--test-concurrency=1", target]);
}

const instrumented = original.replace(
  "const SAMPLE_ROUNDS = 25;",
  "const ciSamples: { wallMs: number; threadCpuMs: number; involuntarySwitches: number; commands: number }[] = [];\nconst SAMPLE_ROUNDS = 25;",
).replace(
  "    const startedAt = process.hrtime.bigint();",
  "    const usageBefore = process.resourceUsage();\n    const cpuBefore = process.threadCpuUsage();\n    const startedAt = process.hrtime.bigint();",
).replace(
  "    assert.equal(document.documentRevision, revisionBeforeBatch + transactions.length);",
  "    const cpuAfter = process.threadCpuUsage(cpuBefore);\n    const usageAfter = process.resourceUsage();\n    ciSamples.push({ wallMs: elapsedMilliseconds, threadCpuMs: (cpuAfter.user + cpuAfter.system) / 1000, involuntarySwitches: usageAfter.involuntaryContextSwitches - usageBefore.involuntaryContextSwitches, commands: transactions.length });\n    assert.equal(document.documentRevision, revisionBeforeBatch + transactions.length);",
).replace(
  "  assert.ok(\n    bestP95Milliseconds < 1,",
  "  context.diagnostic(`CI_SAMPLE_METRICS ${JSON.stringify(ciSamples)}`);\n  assert.ok(\n    bestP95Milliseconds < 1,",
);
if (!instrumented.includes("CI_SAMPLE_METRICS") || !instrumented.includes("ciSamples.push")) {
  throw new Error("Diagnostic instrumentation did not match the baseline");
}

try {
  fs.writeFileSync(target, instrumented);
  run("instrumented-full-parallel", [...nodeTest, "--test-concurrency=4", "scripts/*.test.mjs", "src/**/*.test.{ts,tsx}"]);
  for (let trial = 1; trial <= 3; trial++) {
    run(`instrumented-isolated-${trial}`, [...nodeTest, "--test-concurrency=1", target]);
  }
} finally {
  fs.writeFileSync(target, original);
}

console.log(`Evidence saved to ${output}`);
if (report.runs.some(({ signal, error }) => signal || error)) process.exitCode = 1;
