import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import test from "node:test";

const source = await readFile(new URL("./preload.cjs", import.meta.url), "utf8");
function load(argv, endpoint, extraIpc = {}) {
  let bridge;
  vm.runInNewContext(source, {
    process: { argv, env: { CANDLESCOPE_DESKTOP_BACKEND_PORT: "18080" } },
    require: () => ({ contextBridge: { exposeInMainWorld: (_name, value) => { bridge = value; } }, ipcRenderer: { sendSync(channel) {
      assert.equal(channel, "candlescope:desktop:backend-endpoint");
      return endpoint;
    }, ...extraIpc } }),
  });
  return bridge;
}
test("preload queries the host actual port even without renderer arguments", () => {
  assert.equal(load([], { port: 29123 }).apiBase, "http://127.0.0.1:29123/api/v1");
});
test("host endpoint overrides stale renderer arguments and inherited environment", () => {
  assert.equal(load(["--candlescope-backend-port=18080"], { port: 29124 }).apiBase,
    "http://127.0.0.1:29124/api/v1");
});
test("missing, rejected or invalid host endpoint cannot connect to another service", () => {
  for (const endpoint of [undefined, null, { ok: false, code: "DESKTOP_SENDER_REJECTED" },
    ...[0, 65536, NaN, 1.5, "18080"].map(port => ({ port }))]) {
    assert.throws(() => load(["--candlescope-backend-port=18080"], endpoint), /not configured/);
  }
});

test("extension diagnostics uses the readonly native IPC channel", async () => {
  const calls = [];
  const bridge = load(["--candlescope-backend-port=29123"], { port: 29123 }, { invoke: async (channel) => { calls.push(channel); return { active: [] }; } });
  assert.deepEqual(await bridge.getExtensionDiagnostics(), { active: [] });
  assert.deepEqual(calls, ["candlescope:desktop:extension-diagnostics"]);
});


test("portfolio export exposes only a run-id native download command", async () => {
  const calls = [];
  const bridge = load([], { port: 29123 }, { invoke: async (...args) => { calls.push(args); return { started: true }; } });
  assert.deepEqual(await bridge.downloadReplayPortfolio("run-a"), { started: true });
  assert.deepEqual(calls, [["candlescope:desktop:replay-portfolio-download", "run-a"]]);
});

test("workspace link registration uses its own native channel without a layout snapshot", async () => {
  const calls = [];
  const bridge = load([], { port: 29123 }, { invoke: async (...args) => { calls.push(args); return { ok: true, windowId: "window-2" }; } });
  assert.deepEqual(await bridge.workspaceBusRegisterLinks(), { ok: true, windowId: "window-2" });
  assert.deepEqual(calls, [["candlescope:workspace-bus:register-links"]]);
});

test("Pine transport is delivered from the host endpoint for each window", () => {
  assert.equal(load([], { port: 29123, pineChartTransport: "snapshot" }).pineChartTransport, "snapshot");
  assert.equal(load([], { port: 29124, pineChartTransport: "calculation" }).pineChartTransport, "calculation");
});
test("app appearance is reported on its own channel", () => {
  const sent = [];
  const bridge = load([], { port: 29125 }, { send: (channel, payload) => sent.push([channel, payload]) });
  bridge.setAppearance({ background: "#ffffff" });
  assert.deepEqual(sent, [["candlescope:desktop:appearance", { background: "#ffffff" }]]);
});
