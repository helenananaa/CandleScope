import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import test from "node:test";

const source = await readFile(new URL("./preload.cjs", import.meta.url), "utf8");
function load(argv) {
  let bridge;
  vm.runInNewContext(source, {
    process: { argv, env: { CANDLESCOPE_DESKTOP_BACKEND_PORT: "18080" } },
    require: () => ({ contextBridge: { exposeInMainWorld: (_name, value) => { bridge = value; } }, ipcRenderer: {} }),
  });
  return bridge;
}
test("preload uses the host's actual port instead of the inherited preferred port", () => {
  assert.equal(load(["electron", "--candlescope-backend-port=29123"]).apiBase, "http://127.0.0.1:29123/api/v1");
});
test("missing or invalid endpoint cannot silently connect to another service", () => {
  for (const value of [undefined, "0", "65536", "NaN", "1.5"]) {
    assert.throws(() => load(value === undefined ? [] : [`--candlescope-backend-port=${value}`]), /not configured/);
  }
});
