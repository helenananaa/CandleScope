import assert from "node:assert/strict";
import test from "node:test";
import { mergeSubscriptionRoutes } from "./proxySettingsRuntime.js";
import type { ProxyRouteConfig } from "./proxySettingsRuntime.js";

function route(id: string, url: string): ProxyRouteConfig {
  return { id, name: id, url, egress_group: "shared", enabled: true, exchanges: [], max_concurrency: 4 };
}

test("refresh keeps manual routes, per-node limits and priority while removing deselected nodes", () => {
  const manual = route("manual", "http://127.0.0.1:8080");
  const source = "a".repeat(16);
  const one = route("sub_" + source + "1", "mihomo://old/1");
  const two = route("sub_" + source + "2", "mihomo://old/2");
  const other = route("sub_" + "b".repeat(16) + "1", "mihomo://other/1");
  const three = route("sub_" + source + "3", "mihomo://new/3");
  const saved = [{ ...one, egress_group: "verified", max_concurrency: 1 }, manual, two, other];
  const result = mergeSubscriptionRoutes(saved, [three, { ...one, url: "mihomo://new/1" }], source);
  assert.deepEqual(result, [{ ...saved[0], url: "mihomo://new/1" }, manual, other, three]);
});
