import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { mkdtemp, readFile, readdir } from "node:fs/promises";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { SidecarSupervisor, SidecarStartupError } from "./sidecar-supervisor.mjs";

test("dynamic endpoint stays fixed across restarts and an occupied session port fails closed", async () => {
  const occupied = http.createServer((_q, r) => r.end(JSON.stringify({ desktop_instance_id: "unrelated" })));
  await new Promise(resolve => occupied.listen(0, "127.0.0.1", resolve));
  const preferred = occupied.address().port;
  const root = await mkdtemp(path.join(os.tmpdir(), "candlescope-dynamic-"));
  const source = `
    const http = require('node:http');
    const fs = require('node:fs');
    const id = process.env.CANDLESCOPE_DESKTOP_INSTANCE_ID;
    const server = http.createServer((q,r) => r.end(JSON.stringify({desktop_instance_id:id})));
    server.listen(Number(process.env.CANDLESCOPE_DESKTOP_BOUND_PORT || 0), '127.0.0.1', () => fs.writeFileSync(process.env.CANDLESCOPE_DESKTOP_ENDPOINT_FILE,
      JSON.stringify({port:server.address().port,instanceId:id})));
    process.stdin.resume();
    process.stdin.on('end', () => server.close());
  `;
  const supervisor = new SidecarSupervisor({ command: process.execPath, args: ["-e", source], cwd: root,
    dynamicPort: true, gracefulStdin: true, healthUrl: `http://127.0.0.1:${preferred}/health`,
    healthTimeoutMs: 5000, shutdownTimeoutMs: 1000, logPath: path.join(root, "child.log") });
  let sessionUrl;
  const replacement = http.createServer((_q, r) => r.end("unrelated replacement"));
  try {
    for (let attempt = 0; attempt < 2; attempt++) {
      const result = await supervisor.start();
      assert.notEqual(new URL(result.healthUrl).port, String(preferred));
      assert.equal(result.running, true);
      if (sessionUrl) assert.equal(result.healthUrl, sessionUrl);
      sessionUrl = result.healthUrl;
      assert.deepEqual(await readdir(root), ["child.log"]);
      await supervisor.stop();
      await assert.rejects(fetch(result.healthUrl));
    }
    await new Promise(resolve => replacement.listen(Number(new URL(sessionUrl).port), "127.0.0.1", resolve));
    await assert.rejects(supervisor.start(), SidecarStartupError);
    assert.equal(supervisor.diagnostics().running, false);
    assert.equal(await (await fetch(sessionUrl)).text(), "unrelated replacement");
    assert.deepEqual(await readdir(root), ["child.log"]);
    replacement.closeAllConnections();
    await new Promise(resolve => replacement.close(resolve));
    assert.equal((await supervisor.start()).healthUrl, sessionUrl);
    assert.equal((await (await fetch(`http://127.0.0.1:${preferred}`)).json()).desktop_instance_id, "unrelated");
  } finally {
    await supervisor.stop();
    replacement.closeAllConnections();
    if (replacement.listening) await new Promise(resolve => replacement.close(resolve));
    occupied.closeAllConnections();
    await new Promise(resolve => occupied.close(resolve));
  }
});

test("a mismatched endpoint announcement is never probed and is removed on failure", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "candlescope-bad-endpoint-"));
  let requests = 0;
  const supervisor = new SidecarSupervisor({ command: process.execPath,
    args: ["-e", "require('node:fs').writeFileSync(process.env.CANDLESCOPE_DESKTOP_ENDPOINT_FILE, JSON.stringify({port:18080,instanceId:'wrong'}));setInterval(()=>{},1000)"],
    cwd: root, dynamicPort: true, healthUrl: "http://127.0.0.1:18080/health",
    fetchImpl: () => { requests++; throw new Error("must not probe"); },
    healthTimeoutMs: 300, shutdownTimeoutMs: 1000, logPath: path.join(root, "child.log") });
  await assert.rejects(supervisor.start(), SidecarStartupError);
  assert.equal(requests, 0);
  assert.deepEqual(await readdir(root), ["child.log"]);
  assert.equal(supervisor.diagnostics().running, false);
});

async function freePort() {
  const server = http.createServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  await new Promise((resolve) => server.close(resolve));
  return address.port;
}

test("supervisor starts exactly one child, waits for health, logs, and reclaims it", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "candlescope-sidecar-"));
  const port = await freePort();
  const source = [
    "const http=require('node:http');",
    `const s=http.createServer((q,r)=>{r.statusCode=200;r.end(JSON.stringify({desktop_instance_id:process.env.CANDLESCOPE_DESKTOP_INSTANCE_ID}))});`,
    `s.listen(${port},'127.0.0.1',()=>console.log('ready'));`,
    "process.on('SIGTERM',()=>s.close(()=>process.exit(0)));",
  ].join("");
  const supervisor = new SidecarSupervisor({
    command: process.execPath,
    args: ["-e", source],
    cwd: root,
    env: {},
    healthUrl: `http://127.0.0.1:${port}/health`,
    healthTimeoutMs: 5_000,
    shutdownTimeoutMs: 2_000,
    logPath: path.join(root, "sidecar.log"),
  });
  const first = await supervisor.start();
  const second = await supervisor.start();
  assert.equal(first.pid, second.pid);
  assert.equal(first.running, true);
  await supervisor.stop();
  assert.equal(supervisor.diagnostics().running, false);
  assert.match(await readFile(path.join(root, "sidecar.log"), "utf8"), /ready/);
});

test("startup failure is fail closed and leaves no running child", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "candlescope-sidecar-fail-"));
  const port = await freePort();
  const supervisor = new SidecarSupervisor({
    command: process.execPath,
    args: ["-e", "process.exit(23)"],
    cwd: root,
    env: {},
    healthUrl: `http://127.0.0.1:${port}/health`,
    healthTimeoutMs: 2_000,
    shutdownTimeoutMs: 100,
    logPath: path.join(root, "sidecar.log"),
  });
  await assert.rejects(() => supervisor.start(), SidecarStartupError);
  assert.equal(supervisor.diagnostics().running, false);
});

test("an existing healthy listener cannot impersonate the launched child", async () => {
  const server = http.createServer((_request, response) => response.end(JSON.stringify({ desktop_instance_id: "old-instance" })));
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  const root = await mkdtemp(path.join(os.tmpdir(), "candlescope-stale-sidecar-"));
  const supervisor = new SidecarSupervisor({
    command: process.execPath, args: ["-e", `setTimeout(() => require('node:http').createServer().listen(${port}, '127.0.0.1'), 100)`],
    cwd: root, env: {}, healthUrl: `http://127.0.0.1:${port}/health`, healthTimeoutMs: 1000,
    shutdownTimeoutMs: 100, logPath: path.join(root, "child.log"),
  });
  try {
    await assert.rejects(supervisor.start(), SidecarStartupError);
    assert.equal(supervisor.diagnostics().readyMs, null);
    assert.equal((await fetch(`http://127.0.0.1:${port}/health`)).status, 200);
  } finally {
    await supervisor.stop();
    await new Promise((resolve) => server.close(resolve));
  }
});


test("a stopped sidecar leaves no shutdown timer keeping the host alive", async () => {
  const moduleUrl = new URL("./sidecar-supervisor.mjs", import.meta.url).href;
  const source = `
    import { spawn } from "node:child_process";
    import { once } from "node:events";
    import { SidecarSupervisor } from ${JSON.stringify(moduleUrl)};
    const child = spawn(process.execPath, ["-e", "process.send('ready');setInterval(()=>{},1000)"], {
      stdio: ["ignore", "ignore", "ignore", "ipc"],
    });
    await once(child, "message");
    const supervisor = new SidecarSupervisor({ shutdownTimeoutMs: 15000 });
    supervisor.child = child;
    await supervisor.stop();
    if (child.exitCode === null && child.signalCode === null) throw new Error("child still running");
    console.log("stopped");
  `;
  const { stdout } = await promisify(execFile)(process.execPath, ["--input-type=module", "-e", source], {
    timeout: 2500,
  });
  assert.match(stdout, /stopped/);
});


test("private stdin shutdown runs child cleanup before the process exits", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "candlescope-graceful-"));
  const port = await freePort();
  const logPath = path.join(root, "sidecar.log");
  const source = `
    const http = require('node:http');
    const s = http.createServer((q,r)=>r.end(JSON.stringify({desktop_instance_id:process.env.CANDLESCOPE_DESKTOP_INSTANCE_ID})));
    s.listen(${port}, '127.0.0.1');
    process.stdin.resume();
    process.stdin.on('end',()=>s.close(()=>console.log('graceful cleanup complete')));
  `;
  const supervisor = new SidecarSupervisor({command: process.execPath, args: ["-e", source], cwd: root,
    gracefulStdin: true, healthUrl: `http://127.0.0.1:${port}/health`, healthTimeoutMs: 5000,
    shutdownTimeoutMs: 1500, logPath});
  await supervisor.start();
  await supervisor.stop();
  assert.match(await readFile(logPath, "utf8"), /graceful cleanup complete/);
  await assert.rejects(fetch(`http://127.0.0.1:${port}/health`));
});

test("an unresponsive private-pipe child is still forcibly reclaimed", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "candlescope-graceful-timeout-"));
  const port = await freePort();
  const source = `require('node:http').createServer((q,r)=>r.end(JSON.stringify({desktop_instance_id:process.env.CANDLESCOPE_DESKTOP_INSTANCE_ID}))).listen(${port},'127.0.0.1');`;
  const supervisor = new SidecarSupervisor({command: process.execPath, args: ["-e", source], cwd: root,
    gracefulStdin: true, healthUrl: `http://127.0.0.1:${port}/health`, healthTimeoutMs: 5000,
    shutdownTimeoutMs: 50, logPath: path.join(root, "sidecar.log")});
  await supervisor.start();
  const child = supervisor.child;
  const exited = new Promise(resolve => child.once("exit", resolve));
  await supervisor.stop();
  await exited;
  await assert.rejects(fetch(`http://127.0.0.1:${port}/health`));
});


test("missing executable becomes a startup error instead of an uncaught child error", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "candlescope-no-executable-"));
  const supervisor = new SidecarSupervisor({command: path.join(root, "missing-python.exe"), args: [], cwd: root,
    healthUrl: "http://127.0.0.1:9/health", healthTimeoutMs: 500, shutdownTimeoutMs: 500,
    gracefulStdin: true, logPath: path.join(root, "sidecar.log")});
  await assert.rejects(supervisor.start(), SidecarStartupError);
  assert.equal(supervisor.diagnostics().running, false);
});
