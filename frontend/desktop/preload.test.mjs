import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import test from "node:test";

const source = await readFile(new URL("./preload.cjs", import.meta.url), "utf8");
function load(argv, endpoint) {
  let bridge;
  vm.runInNewContext(source, {
    process: { argv, env: { CANDLESCOPE_DESKTOP_BACKEND_PORT: "18080" } },
    require: () => ({ contextBridge: { exposeInMainWorld: (_name, value) => { bridge = value; } }, ipcRenderer: { sendSync(channel) {
      assert.equal(channel, "candlescope:desktop:backend-endpoint");
      return endpoint;
    } } }),
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
