import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { mkdtemp, readFile, readdir } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { backendStatusPayload, relayBackendStatus } from "./backend-status.mjs";
import { SIDECAR_RESTART_DELAYS_MS, SidecarSupervisor } from "./sidecar-supervisor.mjs";

// A stand-in sidecar: counts its starts, can fail chosen starts before it is
// healthy, can leave a worker behind, and announces a dynamic endpoint the
// way app.desktop_sidecar does.
const SIDECAR = `
  const http = require('node:http');
  const fs = require('node:fs');
  const path = require('node:path');
  const { spawn } = require('node:child_process');
  const root = process.env.TEST_ROOT;
  const countFile = path.join(root, 'starts');
  const count = (fs.existsSync(countFile) ? Number(fs.readFileSync(countFile, 'utf8')) : 0) + 1;
  fs.writeFileSync(countFile, String(count));
  if ((process.env.TEST_FAIL_STARTS || '').split(',').includes(String(count))) process.exit(7);
  if (process.env.TEST_WORKER === '1') {
    // No stdin pipe: only the host's process-group cleanup can stop it.
    const worker = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { stdio: 'ignore' });
    fs.writeFileSync(path.join(root, 'worker-' + count), String(worker.pid));
  }
  const id = process.env.CANDLESCOPE_DESKTOP_INSTANCE_ID;
  const server = http.createServer((q, r) => r.end(JSON.stringify({ desktop_instance_id: id })));
  server.listen(Number(process.env.CANDLESCOPE_DESKTOP_BOUND_PORT || 0), '127.0.0.1', () =>
    fs.writeFileSync(process.env.CANDLESCOPE_DESKTOP_ENDPOINT_FILE,
      JSON.stringify({ port: server.address().port, instanceId: id })));
  process.stdin.resume();
  process.stdin.on('end', () => { server.close(); process.exit(0); });
`;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitFor(predicate, timeoutMs = 10_000) {
  const startedAt = Date.now();
  while (!(await predicate())) {
    if (Date.now() - startedAt > timeoutMs) throw new Error("condition not reached in time");
    await sleep(20);
  }
}

function isAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error.code === "EPERM";
  }
}

async function createSidecar(context, { env = {}, ...options } = {}) {
  const root = await mkdtemp(path.join(os.tmpdir(), "candlescope-restart-"));
  const supervisor = new SidecarSupervisor({
    command: process.execPath, args: ["-e", SIDECAR], cwd: root,
    env: { TEST_ROOT: root, ...env },
    dynamicPort: true, gracefulStdin: true, healthUrl: "http://127.0.0.1:9/health",
    healthTimeoutMs: 5_000, shutdownTimeoutMs: 2_000, orphanGraceMs: 500,
    restartDelaysMs: [50, 50, 50], logPath: path.join(root, "sidecar.log"),
    ...options,
  });
  const statuses = [];
  supervisor.on("status", (status) => statuses.push({ ...status, seenAt: Date.now() }));
  context.after(async () => {
    supervisor.beginQuit();
    await supervisor.stop();
  });
  const starts = async () => Number(await readFile(path.join(root, "starts"), "utf8"));
  return { root, supervisor, statuses, starts };
}

async function killSidecar(supervisor) {
  const child = supervisor.child;
  const exited = new Promise((resolve) => child.once("exit", resolve));
  child.kill("SIGKILL");
  await exited;
  return child.pid;
}

test("the default restart budget is three tries with growing waits", () => {
  assert.equal(SIDECAR_RESTART_DELAYS_MS.length, 3);
  assert.ok(SIDECAR_RESTART_DELAYS_MS.every((ms, index) => index === 0 || ms > SIDECAR_RESTART_DELAYS_MS[index - 1]));
});

test("an unexpected exit after a healthy start is detected and restarted on the same endpoint", async (context) => {
  const { root, supervisor, statuses, starts } = await createSidecar(context);
  const first = await supervisor.start();
  assert.equal(supervisor.status().phase, "running");
  assert.equal(supervisor.status().generation, 1);
  const firstPid = await killSidecar(supervisor);

  await waitFor(() => supervisor.status().phase === "running" && supervisor.status().generation === 2);
  const restarted = supervisor.diagnostics();
  assert.equal(restarted.healthUrl, first.healthUrl, "renderers keep their endpoint");
  assert.notEqual(restarted.pid, firstPid);
  assert.equal(restarted.running, true);
  assert.equal(restarted.restarts, 1);
  assert.equal(await starts(), 2);
  assert.equal((await fetch(restarted.healthUrl)).status, 200);

  const afterKill = statuses.slice(statuses.findIndex((status) => status.phase === "restarting"));
  assert.deepEqual(afterKill.map(({ phase, attempt }) => [phase, attempt]),
    [["restarting", 1], ["restarting", 1], ["restarting", 1], ["running", 0]]);
  assert.deepEqual(afterKill[0].exit && { code: afterKill[0].exit.code, signal: afterKill[0].exit.signal },
    { code: null, signal: "SIGKILL" });
  assert.equal(typeof afterKill[1].retryAt, "string", "the scheduled try is announced");
  assert.equal(afterKill[2].retryAt, null, "then the try itself");

  await supervisor.stop();
  assert.equal(supervisor.status().phase, "stopped");
  assert.deepEqual((await readdir(root)).sort(), ["sidecar.log", "starts"]);
  const log = await readFile(path.join(root, "sidecar.log"), "utf8");
  assert.match(log, /\[desktop\] sidecar exited unexpectedly \(code null, signal SIGKILL\); restarting/);
  assert.match(log, /\[desktop\] sidecar restarted \(attempt 1 of 3\)/);
});

test("restarts back off, stop after the budget, and an explicit restart then recovers", async (context) => {
  const delays = [80, 200, 350];
  const { supervisor, statuses, starts } = await createSidecar(context, {
    env: { TEST_FAIL_STARTS: "2,3,4" }, restartDelaysMs: delays,
  });
  const { healthUrl } = await supervisor.start();
  await killSidecar(supervisor);
  await waitFor(() => supervisor.status().phase === "failed");

  assert.equal(await starts(), 4, "three automatic tries after the first start, no more");
  for (let attempt = 1; attempt <= delays.length; attempt++) {
    const scheduledAt = statuses.findIndex((status) => status.attempt === attempt && status.retryAt);
    const scheduled = statuses[scheduledAt];
    const tried = statuses.slice(scheduledAt + 1).find((status) => status.attempt === attempt
      && status.phase === "restarting" && !status.retryAt);
    assert.ok(tried.seenAt - scheduled.seenAt >= delays[attempt - 1] - 15,
      `try ${attempt} waited ${tried.seenAt - scheduled.seenAt} ms`);
  }
  const failed = supervisor.status();
  assert.equal(failed.attempt, 3);
  assert.equal(failed.maxAttempts, 3);
  assert.match(failed.error, /exited before it became healthy/);
  assert.equal(supervisor.diagnostics().running, false);
  await sleep(450);
  assert.equal(await starts(), 4, "nothing retries after the budget");

  await supervisor.restart();
  assert.equal(supervisor.status().phase, "running");
  assert.equal(supervisor.status().generation, 2);
  assert.equal(supervisor.diagnostics().healthUrl, healthUrl);
  assert.equal(await starts(), 5);
});

test("a sidecar that keeps exiting soon after each restart uses up one budget", async (context) => {
  const { supervisor, starts } = await createSidecar(context, { restartDelaysMs: [20, 20, 20] });
  await supervisor.start();
  for (let generation = 2; generation <= 4; generation++) {
    await killSidecar(supervisor);
    await waitFor(() => supervisor.status().phase === "running" && supervisor.status().generation === generation);
  }
  await killSidecar(supervisor);
  await waitFor(() => supervisor.status().phase === "failed");
  assert.equal(await starts(), 4);
  assert.match(supervisor.status().error, /kept exiting/);

  // A requested restart grants the automatic budget again.
  await supervisor.restart();
  await killSidecar(supervisor);
  await waitFor(() => supervisor.status().phase === "running" && supervisor.status().generation === 6);
  assert.equal(await starts(), 6);
});

test("a sidecar that stayed up long enough gets the full budget for its next exit", async (context) => {
  const { supervisor } = await createSidecar(context, { restartDelaysMs: [20], stableAfterMs: 100 });
  await supervisor.start();
  for (let generation = 2; generation <= 3; generation++) {
    await sleep(150);
    await killSidecar(supervisor);
    await waitFor(() => supervisor.status().phase === "running" && supervisor.status().generation === generation);
  }
});

test("a deliberate stop or a quit never restarts the sidecar", async (context) => {
  const stopped = await createSidecar(context, { restartDelaysMs: [20] });
  await stopped.supervisor.start();
  await stopped.supervisor.stop();
  await sleep(250);
  assert.equal(await stopped.starts(), 1);
  assert.equal(stopped.supervisor.status().phase, "stopped");
  assert.equal(stopped.statuses.some((status) => status.phase === "restarting"), false);

  const quitting = await createSidecar(context, { restartDelaysMs: [20] });
  await quitting.supervisor.start();
  quitting.supervisor.beginQuit();
  await killSidecar(quitting.supervisor);
  await sleep(250);
  assert.equal(await quitting.starts(), 1);
  assert.equal(quitting.statuses.some((status) => status.phase === "restarting"), false);
  await assert.rejects(quitting.supervisor.start(), /cancelled/);
  await assert.rejects(quitting.supervisor.restart(), /cancelled/);

  // Quitting while a restart waits for its turn cancels that restart.
  const pending = await createSidecar(context, { restartDelaysMs: [300] });
  await pending.supervisor.start();
  await killSidecar(pending.supervisor);
  await waitFor(() => Boolean(pending.supervisor.status().retryAt));
  pending.supervisor.beginQuit();
  await pending.supervisor.stop();
  await sleep(450);
  assert.equal(await pending.starts(), 1);
  assert.equal(pending.supervisor.diagnostics().running, false);
});

test("a stop during a restart try cancels it and leaves no sidecar running", async (context) => {
  const { supervisor, statuses } = await createSidecar(context, { restartDelaysMs: [0] });
  await supervisor.start();
  await killSidecar(supervisor);
  await waitFor(() => statuses.some((status) => status.phase === "restarting" && !status.retryAt));
  await supervisor.stop();
  await sleep(200);
  assert.equal(supervisor.diagnostics().running, false);
  assert.equal(supervisor.status().phase, "stopped");
});

test("workers a killed sidecar leaves behind are reclaimed before the restart and on stop",
  { skip: process.platform === "win32" && "process groups are POSIX only" }, async (context) => {
    const { root, supervisor } = await createSidecar(context, { env: { TEST_WORKER: "1" } });
    await supervisor.start();
    const firstWorker = Number(await readFile(path.join(root, "worker-1"), "utf8"));
    assert.equal(isAlive(firstWorker), true);
    await killSidecar(supervisor);
    await waitFor(() => supervisor.status().phase === "running" && supervisor.status().generation === 2);
    await waitFor(() => !isAlive(firstWorker), 3_000);

    const secondWorker = Number(await readFile(path.join(root, "worker-2"), "utf8"));
    assert.equal(isAlive(secondWorker), true);
    await supervisor.stop();
    await waitFor(() => !isAlive(secondWorker), 3_000);
  });

test("pages are told each backend phase without host process details", async (context) => {
  const { supervisor } = await createSidecar(context);
  const sent = [];
  const unsubscribe = relayBackendStatus(supervisor, (status) => sent.push(status));
  await supervisor.start();
  await killSidecar(supervisor);
  await waitFor(() => sent.some((status) => status.phase === "running" && status.generation === 2));

  const phases = sent.map((status) => status.phase);
  assert.deepEqual(phases, ["running", "restarting", "restarting", "restarting", "running"]);
  const keys = ["attempt", "error", "exit", "generation", "maxAttempts", "phase", "retryAt"];
  for (const status of sent) assert.deepEqual(Object.keys(status).sort(), keys);
  assert.deepEqual(sent[1].exit, { code: null, signal: "SIGKILL" });
  assert.equal(sent[1].maxAttempts, 3);

  unsubscribe();
  await supervisor.stop();
  assert.equal(sent.at(-1).phase, "running", "no event after unsubscribe");
});

test("backend status payloads accept only known phases and bounded fields", () => {
  assert.deepEqual(backendStatusPayload({
    phase: "evil", generation: 1.5, attempt: "2", maxAttempts: 3, retryAt: 4,
    error: "x".repeat(900), exit: { code: "1", signal: 9 }, pid: 42, logPath: "/private",
  }), {
    phase: "stopped", generation: 0, attempt: 0, maxAttempts: 3, retryAt: null,
    error: "x".repeat(500), exit: { code: null, signal: null },
  });
  const supervisor = new EventEmitter();
  const sent = [];
  const unsubscribe = relayBackendStatus(supervisor, (status) => sent.push(status));
  supervisor.emit("status", { phase: "failed", generation: 3, attempt: 3, maxAttempts: 3, error: "port in use" });
  unsubscribe();
  supervisor.emit("status", { phase: "running" });
  assert.deepEqual(sent.map(({ phase, error }) => [phase, error]), [["failed", "port in use"]]);
});
