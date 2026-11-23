import assert from "node:assert/strict";
import test from "node:test";
import { fetchUnifiedCommands, invokeUnifiedCommand } from "../pluginPlatformApi.js";
import { buildPluginRegistries } from "../pluginRegistries.js";

test("unified commands populate the palette and invoke the exact instance with full-size results", async () => {
  const apiBase = "http://127.0.0.1:8000/api/v2/plugins";
  const pluginId = "candlescope.aho-corasick";
  const instanceId = "b".repeat(32);
  const identity = { pluginId, generation: 2, version: "0.2.1", packageSha256: `sha256:${"a".repeat(64)}` };
  const exampleInput = { patterns: ["波浪"], haystack: "波浪" };
  const matches = Array.from({ length: 10_000 }, (_, startByte) => ({ startByte, endByte: startByte + 1, patternIndex: 0 }));
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const originalFetch = globalThis.fetch;
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      __CANDLESCOPE_PLUGIN_MANAGEMENT_V1__: { apiBase, sessionToken: "a".repeat(32), csrfToken: "b".repeat(32) },
    },
  });
  let instance = instanceId;
  globalThis.fetch = async (url, request) => {
    if (String(url) === `${apiBase}/manage/unified/commands`) {
      assert.equal(request?.method, "GET");
      return Response.json({ commands: [{ id: "search", title: "Search", entryId: "main", pluginId, identity, instanceId, exampleInput }] });
    }
    assert.equal(String(url), `${apiBase}/manage/unified/commands/invoke`);
    assert.ok(new Headers(request?.headers).has("X-CandleScope-User-Action"));
    assert.deepEqual(JSON.parse(String(request?.body)), { pluginId, commandId: "search", identity, instanceId, input: exampleInput });
    return Response.json({ identity, instanceId: instance, result: { matches } });
  };
  try {
    const [command] = buildPluginRegistries(null, undefined, await fetchUnifiedCommands()).commandPalette;
    assert.ok(command?.unifiedTarget);
    assert.equal(command.id, `${pluginId}/search`);
    assert.deepEqual(command.exampleInput, exampleInput);
    assert.deepEqual(await invokeUnifiedCommand(command.unifiedTarget, exampleInput), { matches });
    instance = "c".repeat(32);
    await assert.rejects(invokeUnifiedCommand(command.unifiedTarget, exampleInput), /identity changed/);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow) Object.defineProperty(globalThis, "window", originalWindow);
    else Reflect.deleteProperty(globalThis, "window");
  }
});
