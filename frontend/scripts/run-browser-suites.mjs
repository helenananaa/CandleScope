/**
 * Runs the `*.browser.ts(x)` suites in a real Chrome, one fixture at a time,
 * through `frontend-script-integration.mjs`. `npm test` only finds
 * `*.test.{ts,tsx}`, so these suites have no other automatic runner.
 *
 * Every suite must be imported by a fixture that runs here, or by a fixture in
 * EXCLUDED with the reason it cannot run in CI. A new suite or fixture that is
 * neither fails `run-browser-suites.test.mjs` instead of being skipped silently.
 *
 * A fixture with a `backend` needs a Python fixture server. The runner starts
 * it from backend/ on a free loopback port, waits until it answers, passes its
 * address to the harness, and stops it with SIGINT afterwards. Those fixtures
 * form the "python" group; `--python` (or CANDLESCOPE_TEST_PYTHON) names an
 * interpreter with the backend requirements installed.
 */
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";

const FRONTEND = fileURLToPath(new URL("../", import.meta.url));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const uvicorn = (source, app) => ({
  source,
  args: (port) => ["-m", "uvicorn", app, "--host", "127.0.0.1", "--port", String(port)],
  ready: "/api/v1/fixture/state",
  harnessEnv: (port) => ({ VITE_API_BASE: `http://127.0.0.1:${port}/api/v1` }),
});

/** Python fixture servers, each started from backend/ by the fixtures that name it. */
export const BACKENDS = {
  synthetic: uvicorn("tests/synthetic_browser_server.py", "tests.synthetic_browser_server:app"),
  "synthetic-pinned": uvicorn("tests/synthetic_pinned_browser_server.py", "tests.synthetic_pinned_browser_server:app"),
  "chart-indicator": uvicorn("tests/chart_indicator_browser_server.py", "tests.chart_indicator_browser_server:app"),
  "chart-calculation": {
    source: "tests/chart_calculation_browser_server.py",
    args: (port, scratch) => ["-m", "tests.chart_calculation_browser_server", path.join(scratch, "fixtures"), String(port)],
    ready: "/api/v1/fixture/state",
    harnessEnv: (port) => ({ VITE_API_BASE: `http://127.0.0.1:${port}/api/v1` }),
  },
  "replay-notes": {
    source: "tests/replay_notes_browser_server.py",
    args: () => ["-m", "tests.replay_notes_browser_server"],
    env: (port, scratch) => ({ CANDLESCOPE_NOTE_QA_ROOT: path.join(scratch, "notes"), CANDLESCOPE_NOTE_QA_PORT: String(port) }),
    ready: "/fixture/state",
    harnessEnv: (port) => ({ CANDLESCOPE_QA_BACKEND_URL: `http://127.0.0.1:${port}` }),
  },
};

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
  { flag: "--replay-notes", fixture: "replay-notes-browser.html", backend: "replay-notes" },
  { flag: "--backend-synthetic", fixture: "backend-synthetic-browser.html", backend: "synthetic" },
  { flag: "--backend-synthetic-pinned", fixture: "backend-synthetic-pinned-browser.html", backend: "synthetic-pinned" },
  { flag: "--chart-indicator", fixture: "chart-indicator-browser.html", backend: "chart-indicator" },
  { flag: "--chart-calculation", fixture: "chart-calculation-browser.html", backend: "chart-calculation" },
  { flag: "--chart-market-calculation", fixture: "chart-market-calculation-browser.html", backend: "chart-calculation" },
  { flag: "--chart-market-prepend", fixture: "chart-market-prepend-browser.html", backend: "chart-calculation" },
];

/** Fixtures that do not run in CI, each with the reason. */
export const EXCLUDED = {};

export const GROUPS = {
  browser: (item) => !item.backend,
  python: (item) => Boolean(item.backend),
  all: () => true,
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
  for (const { fixture, backend } of RUN) {
    if (backend !== undefined && !Object.hasOwn(BACKENDS, backend)) problems.push(`${fixture} names unknown backend ${backend}`);
  }
  for (const [name, { source }] of Object.entries(BACKENDS)) {
    if (!fs.existsSync(path.join(frontend, "..", "backend", source))) problems.push(`backend ${name} source backend/${source} does not exist`);
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
  return { fixtures, suites, run, excluded, imports, problems };
}

async function freePort() {
  return await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

/** Starts a fixture server; resolves once it answers, with its harness env and a stop(). */
async function startBackend(name, directory, frontend, python) {
  const spec = BACKENDS[name];
  const backend = path.join(frontend, "..", "backend");
  const scratch = path.join(directory, "backend");
  const data = path.join(scratch, "data");
  fs.mkdirSync(data, { recursive: true });
  const port = await freePort();
  const log = fs.openSync(path.join(directory, "server.log"), "w");
  const env = { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONUNBUFFERED: "1",
    PYTHONPATH: [backend, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
    DATA_DIR: data, CANDLE_DATA_DIR: data, ...spec.env?.(port, scratch) };
  // Its own process group, so a server that ignores SIGINT is killed with its workers.
  const child = spawn(python, spec.args(port, scratch), { cwd: backend, env, stdio: ["ignore", log, log],
    detached: process.platform !== "win32", windowsHide: true });
  fs.closeSync(log);
  let spawnError = null;
  const exited = new Promise((resolve) => {
    child.on("error", (error) => { spawnError = error; resolve({ code: null, signal: null }); });
    child.on("exit", (code, signal) => resolve({ code, signal }));
  });
  const running = () => !spawnError && child.exitCode === null && child.signalCode === null;
  const stop = async () => {
    if (running()) child.kill("SIGINT");
    let timer;
    const result = await Promise.race([exited, new Promise((resolve) => { timer = setTimeout(resolve, 30_000, null); })]);
    clearTimeout(timer);
    if (result) return result;
    try { process.platform === "win32" ? child.kill("SIGKILL") : process.kill(-child.pid, "SIGKILL"); } catch { /* already gone */ }
    return { ...(await exited), killed: true };
  };
  const url = `http://127.0.0.1:${port}${spec.ready}`;
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    if (!running()) throw new Error(`fixture server ${name} exited before it was ready${spawnError ? `: ${spawnError.message}` : ""}; see server.log`);
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(2000) });
      if (response.ok) return { env: spec.harnessEnv(port), stop };
    } catch { /* not listening yet */ }
    await sleep(250);
  }
  await stop();
  throw new Error(`fixture server ${name} did not answer ${url} within 120 s; see server.log`);
}

async function runFixture(item, output, frontend, python) {
  const { flag, fixture, backend } = item;
  const name = fixture.replace(/-browser\.html$/, "");
  const directory = path.join(output, name);
  fs.rmSync(directory, { recursive: true, force: true });
  fs.mkdirSync(directory, { recursive: true });
  const started = performance.now();
  let server = null;
  if (backend) {
    try { server = await startBackend(backend, directory, frontend, python); } catch (error) {
      return { fixture, flag, backend, passed: false, seconds: Math.round(performance.now() - started) / 1000, error: String(error.message) };
    }
  }
  const result = await runHarness(item, directory, frontend, server?.env ?? {}, started);
  if (!server) return result;
  const stopped = await server.stop();
  // A clean exit means nothing hung and the server's own shutdown checks passed:
  // uvicorn still exits 0 when the lifespan shutdown raises, but logs it.
  const log = fs.readFileSync(path.join(directory, "server.log"), "utf8");
  const clean = stopped.code === 0 && !stopped.killed && !log.includes("Application shutdown failed");
  return { ...result, backend, serverExit: stopped, passed: result.passed && clean,
    error: result.error ?? (clean ? null : `fixture server ${backend} did not stop cleanly (${JSON.stringify(stopped)}); see server.log`) };
}

function runHarness({ flag, fixture }, directory, frontend, env, started) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, ["scripts/frontend-script-integration.mjs", ...(flag ? [flag] : []), "--out", directory],
      { cwd: frontend, env: { ...process.env, ...env }, stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
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
  let only = null, list = false, group = "browser";
  let python = process.env.CANDLESCOPE_TEST_PYTHON || (process.platform === "win32" ? "python" : "python3");
  for (let index = 0; index < argv.length; index++) {
    if (argv[index] === "--out") output = path.resolve(argv[++index]);
    else if (argv[index] === "--only") only = new Set(argv[++index].split(","));
    else if (argv[index] === "--group") group = argv[++index];
    else if (argv[index] === "--python") python = argv[++index];
    else if (argv[index] === "--list") list = true;
    else throw new Error(`Unknown option: ${argv[index]}`);
  }
  if (!Object.hasOwn(GROUPS, group)) throw new Error(`--group must be one of ${Object.keys(GROUPS).join(", ")}`);
  const found = inventory(frontend);
  if (found.problems.length) {
    process.stderr.write(`Browser suite inventory is incomplete:\n${found.problems.map((line) => `  ${line}`).join("\n")}\n`);
    return 2;
  }
  // --only picks fixtures by name from every group.
  const selected = only ? RUN.filter((item) => only.has(item.fixture.replace(/-browser\.html$/, ""))) : RUN.filter(GROUPS[group]);
  if (only && selected.length !== only.size) throw new Error(`--only names a fixture that does not run: ${[...only].join(", ")}`);
  const covered = new Set(selected.flatMap((item) => found.imports.get(item.fixture)));
  const elsewhere = RUN.filter((item) => !selected.includes(item));
  const otherSuites = found.run.filter((suite) => !covered.has(suite));
  const label = only ? "--only" : `group ${group}`;
  process.stdout.write(`Browser suites in this run, ${label} (${covered.size}/${found.suites.length}):\n${[...covered].sort().map((suite) => `  ${suite}`).join("\n")}\n`);
  process.stdout.write(`Browser suites that run in another group (${otherSuites.length}):\n${otherSuites.map((suite) => {
    const owners = elsewhere.filter((item) => found.imports.get(item.fixture).includes(suite));
    return `  ${suite} (${owners.map((item) => item.backend ? `python: ${item.fixture} with backend ${item.backend}` : `browser: ${item.fixture}`).join("; ")})`;
  }).join("\n")}\n`);
  process.stdout.write(`Browser suites not run (${found.excluded.length}):\n${found.excluded.map(({ suite, reasons }) => `  ${suite}\n${reasons.map((reason) => `    ${reason}`).join("\n")}`).join("\n")}\n`);
  if (list) return 0;
  fs.mkdirSync(output, { recursive: true });
  const results = [];
  for (const item of selected) {
    process.stdout.write(`\n[browser] ${item.fixture} ${item.flag ?? "(default)"}${item.backend ? ` with backend ${item.backend}` : ""}\n`);
    const result = await runFixture(item, output, frontend, python);
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
