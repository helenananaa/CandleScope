import fs from "node:fs";
import path from "node:path";
import { once } from "node:events";
import { run } from "node:test";
import { spec } from "node:test/reporters";
import { fileURLToPath, pathToFileURL } from "node:url";

const DEFAULT_PATTERNS = ["scripts/*.test.mjs", "src/**/*.test.{ts,tsx}"];
const PERFORMANCE_TEST = "src/features/drawings/core/__tests__/drawingCommandPerformance.test.ts";
const TEST_IMPORTS = [
  "--import", fileURLToPath(new URL("./monaco-esm-loader.mjs", import.meta.url)),
  "--import", import.meta.resolve("tsx"),
];

export async function main(args, cwd = process.cwd()) {
  let workers = 4;
  const patterns = [];
  for (let index = 0; index < args.length; index++) {
    if (args[index] === "--workers") workers = Number(args[++index]);
    else if (args[index].startsWith("-")) throw new Error(`Unknown option: ${args[index]}`);
    else patterns.push(args[index]);
  }
  if (!Number.isInteger(workers) || workers < 1 || workers > 32) {
    throw new Error("--workers must be an integer from 1 to 32");
  }
  const files = [...new Set(fs.globSync(patterns.length ? patterns : DEFAULT_PATTERNS, { cwd })
    .map((file) => path.resolve(cwd, file)))].sort();
  if (!files.length) throw new Error("No frontend tests matched; no test result was produced");
  const performanceTest = path.resolve(cwd, PERFORMANCE_TEST);
  const stages = [
    { name: "functional", files: files.filter((file) => file !== performanceTest), concurrency: workers },
    { name: "isolated performance gate", files: files.filter((file) => file === performanceTest), concurrency: 1 },
  ];
  let failed = false;
  for (const stage of stages) {
    if (!stage.files.length) continue;
    process.stdout.write(`\n[frontend] ${stage.name}: ${stage.files.length} files, concurrency=${stage.concurrency}\n`);
    // Wait for every functional test process to exit before starting the wall-clock
    // benchmark. Its 1ms gate must not include contention from our own test workers.
    const stream = run({ files: stage.files, cwd, concurrency: stage.concurrency, execArgv: TEST_IMPORTS });
    stream.on("test:fail", () => { failed = true; });
    for await (const chunk of stream.compose(new spec())) {
      if (!process.stdout.write(chunk)) await once(process.stdout, "drain");
    }
  }
  return failed ? 1 : 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main(process.argv.slice(2)).then((code) => { process.exitCode = code; }).catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 2;
  });
}
