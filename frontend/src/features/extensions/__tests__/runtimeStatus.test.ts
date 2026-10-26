import assert from "node:assert/strict";
import test from "node:test";
import { extensionRuntimeStatus } from "../runtimeStatus.js";
import type { ExtensionRecord } from "../contracts.js";

const item: ExtensionRecord = { manifest: { id: "example.runtime", name: "Example", version: "1.1.0",
  apiVersion: 1, schema: "candlescope.extension/1", trust: "full-trust", entries: { backend: "backend.py" } },
  digest: "new", generation: 2, enabled: true, history: [], error: null };
const running = { id: item.manifest.id, version: "1.1.0", digest: "new", generation: 2 };

test("desired state cannot masquerade as the running backend version", () => {
  assert.equal(extensionRuntimeStatus(item, "backend", [], undefined, false), "pending-start");
  assert.equal(extensionRuntimeStatus(item, "backend", [running], undefined, false), "running");
  assert.equal(extensionRuntimeStatus(item, "backend", [{ ...running, digest: "old", version: "1.0.0" }], undefined, false), "pending-restart");
  assert.equal(extensionRuntimeStatus(item, "backend", [{ ...running, generation: 1 }], undefined, false), "pending-restart");
  assert.equal(extensionRuntimeStatus({ ...item, enabled: false }, "backend", [running], undefined, false), "pending-stop");
  assert.equal(extensionRuntimeStatus({ ...item, enabled: false }, "backend", [], undefined, false), "stopped");
});

test("failure, missing diagnostics and recovery remain distinguishable", () => {
  assert.equal(extensionRuntimeStatus(item, "backend", [], "activation failure", false), "failed");
  assert.equal(extensionRuntimeStatus(item, "backend", undefined, undefined, false), "unavailable");
  assert.equal(extensionRuntimeStatus(item, "backend", [], "old failure", true), "safe-mode");
  assert.equal(extensionRuntimeStatus({ ...item, manifest: { ...item.manifest, entries: {} } }, "backend", [running], undefined, false), "pending-stop");
});
