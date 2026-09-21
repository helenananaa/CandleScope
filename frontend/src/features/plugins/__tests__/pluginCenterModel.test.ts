import assert from "node:assert/strict";
import test from "node:test";
import { filterPlugins, pluginStatus } from "../pluginCenterModel.js";
import type { PluginCatalogPlugin } from "../pluginPlatformTypes.js";
const plugin = (overrides: Partial<PluginCatalogPlugin> = {}): PluginCatalogPlugin => ({
  id: "test.scanner", name: "Scanner", publisher: "Example", version: "1.0.0", state: "active", enabled: true, available: true, trustLevel: "local-developer",
  permissions: { activationReady: true, requiredSatisfied: true, requiredPermissionIds: [], permissions: [] }, contributions: [], runtime: { entrypoints: [{ entrypointId: "main", state: "stopped", generation: 0 }] }, ...overrides,
});
test("on-demand stopped entrypoints remain enabled; failed or unavailable plugins require attention", () => {
  assert.equal(pluginStatus(plugin()), "active");
  assert.equal(pluginStatus(plugin({ available: false })), "attention");
  assert.equal(pluginStatus(plugin({ state: "disabled", available: false })), "disabled");
  assert.equal(pluginStatus(plugin({ runtime: { entrypoints: [{ entrypointId: "main", state: "failed", generation: 1 }] } })), "attention");
});
test("filters preserve lifecycle and authorization distinctions and search authors case-insensitively", () => {
  const active = plugin();
  const staged = plugin({ id: "test.staged", state: "staged", available: false });
  const permissions = plugin({ id: "test.permissions", permissions: { ...active.permissions, activationReady: false } });
  assert.deepEqual(filterPlugins([active, staged, permissions], " EXAMPLE ", "attention").map((item) => item.id), [staged.id, permissions.id]);
  assert.deepEqual(filterPlugins([active, staged], "test.scanner", "active"), [active]);
  assert.deepEqual(filterPlugins([active], "unknown", "all"), []);
});
