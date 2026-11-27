/**
 * Runs the `*.browser.ts(x)` suites in a real Chrome, one fixture at a time,
 * through `frontend-script-integration.mjs`. `npm test` only finds
 * `*.test.{ts,tsx}`, so these suites have no other automatic runner.
 *
 * Every suite must be imported by a fixture that runs here, or by a fixture in
 * EXCLUDED with the reason it cannot run in CI. A new suite or fixture that is
 * neither fails `run-browser-suites.test.mjs` instead of being skipped silently.
 */
import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";

const FRONTEND = fileURLToPath(new URL("../", import.meta.url));

/** Fixtures run in CI: the harness flag and the fixture page it builds. */
export const RUN = [
  { flag: "--replay-visible", fixture: "replay-visible-indicators-browser.html" },
  { flag: "--replay-resize", fixture: "replay-resize-browser.html" },
  { flag: "--replay-training-input", fixture: "replay-training-input-browser.html" },
  { flag: "--quick-replay-step", fixture: "quick-replay-step-browser.html" },
  { flag: "--account-overlays", fixture: "chart-account-overlays-browser.html" },
  { flag: "--practice-order-ticket", fixture: "practice-order-ticket-browser.html" },
  { flag: "--chart-viewport", fixture: "chart-viewport-browser.html" },
  { flag: "--history-stages", fixture: "history-stages-browser.html" },
  { flag: "--chart-time-navigation", fixture: "chart-time-navigation-browser.html" },
  { flag: "--chart-reopen-live-tail", fixture: "chart-reopen-live-tail-browser.html" },
  { flag: "--chart-first-fit", fixture: "chart-first-fit-browser.html" },
  { flag: "--interval-admission", fixture: "interval-admission-browser.html" },
  { flag: "--market-health", fixture: "market-health-browser.html" },
  { flag: "--indicator-flow", fixture: "indicator-flow-browser.html" },
  { flag: "--annotation-tools", fixture: "annotation-tools-browser.html" },
  { flag: "--range-measure", fixture: "range-measure-browser.html" },
  { flag: null, fixture: "frontend-script-browser.html" },
];

/** Fixtures that do not run in CI, each with the reason. */
export const EXCLUDED = {
  "backend-synthetic-browser.html": "needs the Python fixture backend backend/tests/synthetic_browser_server.py behind VITE_API_BASE",
  "backend-synthetic-pinned-browser.html": "needs the Python fixture backend backend/tests/synthetic_pinned_browser_server.py behind VITE_API_BASE",
  "chart-indicator-browser.html": "needs the Python fixture backend backend/tests/chart_indicator_browser_server.py behind VITE_API_BASE",
  "chart-calculation-browser.html": "needs a Python chart-calculation fixture backend (/fixture/bars, /fixture/state); the only one is QA evidence under docs/qa",
  "chart-market-calculation-browser.html": "needs a Python chart-calculation fixture backend (/fixture/bars, /fixture/seed-left); the only one is QA evidence under docs/qa",
  "chart-market-prepend-browser.html": "needs a Python chart-calculation fixture backend (/fixture/bars, /fixture/seed-left); the only one is QA evidence under docs/qa",
  "replay-notes-browser.html": "needs the Python replay notes backend docs/qa/replay-time-notes-20261104/http_server.py at CANDLESCOPE_QA_BACKEND_URL",
};

const slash = (value) => value.replaceAll("\\", "/");

function walk(directory, predicate, root = directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) return entry.name === "node_modules" ? [] : walk(file, predicate, root);
    const relative = slash(path.relative(root, file));
    return predicate(relative) ? [relative] : [];
  });
}

/** Which fixture imports each browser suite, and which suites run. */
export function inventory(frontend = FRONTEND) {
  const fixtures = fs.readdirSync(path.join(frontend, "scripts")).filter((name) => name.endsWith("-browser.html")).sort();
  const suites = walk(path.join(frontend, "src"), (name) => /\.browser\.tsx?$/.test(name)).map((name) => `src/${name}`).sort();
  const imports = new Map(fixtures.map((fixture) => {
    const html = fs.readFileSync(path.join(frontend, "scripts", fixture), "utf8");
    return [fixture, [...html.matchAll(/from\s+["']\/(src\/[^"']+\.browser\.tsx?)["']/g)].map((match) => match[1])];
  }));
  const running = new Set(RUN.map((item) => item.fixture));
  const problems = [];
  for (const fixture of fixtures) {
    if (running.has(fixture) && Object.hasOwn(EXCLUDED, fixture)) problems.push(`${fixture} is both run and excluded`);
    if (!running.has(fixture) && !EXCLUDED[fixture]?.trim()) problems.push(`${fixture} is neither run nor excluded with a reason`);
  }
  for (const fixture of [...running, ...Object.keys(EXCLUDED)]) {
    if (!fixtures.includes(fixture)) problems.push(`${fixture} is listed but does not exist`);
  }
  const run = [], excluded = [];
  for (const suite of suites) {
    const owners = fixtures.filter((fixture) => imports.get(fixture).includes(suite));
    if (!owners.length) problems.push(`${suite} is not imported by any scripts/*-browser.html fixture`);
    else if (owners.some((fixture) => running.has(fixture))) run.push(suite);
    else excluded.push({ suite, reasons: owners.map((fixture) => `${fixture}: ${EXCLUDED[fixture]}`) });
  }
  for (const [fixture, list] of imports) {
    for (const suite of list) if (!suites.includes(suite)) problems.push(`${fixture} imports missing ${suite}`);
  }
  return { fixtures, suites, run, excluded, problems };
}

function runFixture({ flag, fixture }, output, frontend) {
  const name = fixture.replace(/-browser\.html$/, "");
  const directory = path.join(output, name);
  fs.rmSync(directory, { recursive: true, force: true });
  fs.mkdirSync(directory, { recursive: true });
  const started = performance.now();
  return new Promise((resolve) => {
    const child = spawn(process.execPath, ["scripts/frontend-script-integration.mjs", ...(flag ? [flag] : []), "--out", directory],
      { cwd: frontend, stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
    const log = fs.createWriteStream(path.join(directory, "harness.log"));
    child.stdout.pipe(log); child.stderr.pipe(log);
    child.on("close", (code) => {
      let receipt = null;
      try { receipt = JSON.parse(fs.readFileSync(path.join(directory, "result.json"), "utf8")); } catch { /* the harness did not finish */ }
      // The harness owns the build output; only the receipt and logs are evidence.
      fs.rmSync(path.join(directory, "dist"), { recursive: true, force: true });
      for (const entry of fs.readdirSync(directory)) {
        if (entry.startsWith("browser-profile-")) fs.rmSync(path.join(directory, entry), { recursive: true, force: true });
      }
      const passed = code === 0 && receipt?.passed === true && receipt.fixture === fixture;
      const error = passed ? null : receipt?.fixture && receipt.fixture !== fixture
        ? `the harness built ${receipt.fixture}, not ${fixture}`
        : String(receipt?.error ?? `harness exited ${code}`).slice(0, 2000);
      resolve({ fixture, flag, passed, seconds: Math.round(performance.now() - started) / 1000, error });
    });
  });
}

export async function main(argv, frontend = FRONTEND) {
  let output = path.join(frontend, "..", "output", "browser-suites");
  let only = null, list = false;
  for (let index = 0; index < argv.length; index++) {
    if (argv[index] === "--out") output = path.resolve(argv[++index]);
    else if (argv[index] === "--only") only = new Set(argv[++index].split(","));
    else if (argv[index] === "--list") list = true;
    else throw new Error(`Unknown option: ${argv[index]}`);
  }
  const found = inventory(frontend);
  if (found.problems.length) {
    process.stderr.write(`Browser suite inventory is incomplete:\n${found.problems.map((line) => `  ${line}`).join("\n")}\n`);
    return 2;
  }
  process.stdout.write(`Browser suites run (${found.run.length}/${found.suites.length}):\n${found.run.map((suite) => `  ${suite}`).join("\n")}\n`);
  process.stdout.write(`Browser suites not run (${found.excluded.length}):\n${found.excluded.map(({ suite, reasons }) => `  ${suite}\n${reasons.map((reason) => `    ${reason}`).join("\n")}`).join("\n")}\n`);
  if (list) return 0;
  const selected = only ? RUN.filter((item) => only.has(item.fixture.replace(/-browser\.html$/, ""))) : RUN;
  if (only && selected.length !== only.size) throw new Error(`--only names a fixture that does not run: ${[...only].join(", ")}`);
  fs.mkdirSync(output, { recursive: true });
  const results = [];
  for (const item of selected) {
    process.stdout.write(`\n[browser] ${item.fixture} ${item.flag ?? "(default)"}\n`);
    const result = await runFixture(item, output, frontend);
    results.push(result);
    process.stdout.write(`[browser] ${result.passed ? "PASS" : "FAIL"} ${item.fixture} in ${result.seconds}s${result.error ? `\n${result.error}` : ""}\n`);
    fs.writeFileSync(path.join(output, "summary.json"), `${JSON.stringify({ run: found.run, excluded: found.excluded, results }, null, 2)}\n`);
  }
  const failed = results.filter((result) => !result.passed);
  process.stdout.write(`\n${results.length - failed.length}/${results.length} browser fixtures passed. Evidence: ${output}\n`);
  return failed.length ? 1 : 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main(process.argv.slice(2)).then((code) => { process.exitCode = code; }).catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 2;
  });
}
