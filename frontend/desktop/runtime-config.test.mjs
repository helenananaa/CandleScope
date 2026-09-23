import assert from "node:assert/strict";
import test from "node:test";
import { desktopBackendEnvironment, desktopRuntimeConfigPlugin } from "./runtime-config.mjs";

for (const enabled of ["1", "0", undefined, "", "true", "invalid"]) {
  test(`packaged backend agrees with Vite's resolved batch-stream flag (${enabled})`, () => {
    const plugin = desktopRuntimeConfigPlugin();
    plugin.configResolved({ env: { VITE_KLINE_BATCH_STREAM_ENABLED: enabled } });
    let artifact;
    plugin.generateBundle.call({ emitFile(value) { artifact = value; } });
    assert.equal(artifact.fileName, "desktop-runtime-config.json");
    assert.deepEqual(desktopBackendEnvironment(JSON.parse(artifact.source)), {
      KLINE_BATCH_STREAM_ENABLED: enabled === undefined || enabled === "1" ? "1" : "0",
    });
  });
}

test("an invalid packaged runtime contract fails explicitly", () => {
  for (const value of [null, {}, { schemaVersion: 1, klineBatchStreamEnabled: "1" }]) {
    assert.throws(() => desktopBackendEnvironment(value), /Invalid desktop runtime configuration/);
  }
});
