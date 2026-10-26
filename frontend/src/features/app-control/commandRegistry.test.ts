import assert from "node:assert/strict";
import test from "node:test";
import { AppCommandRegistry, command, contextReference } from "./commandRegistry.js";
import { empty, number, object, record } from "./commandSchema.js";
import type { ControlRequest } from "./controlModel.js";

function fixture() {
  const registry = new AppCommandRegistry(); let value = 0; let calls = 0; let enabled = true;
  const remove = registry.register({ id: "demo", title: "Demo", context: () => ({ value }), snapshot: () => ({ value }), commands: [
    command("set", "Set", object({ value: number(0, 100, true) }), (args) => { calls++; value = args.value; }, { available: () => enabled }),
    command("read", "Read", empty, () => value, { readOnly: true }),
  ] });
  const request = (command: string, args = {}, method = "app.execute"): ControlRequest => ({ id: "edit", method,
    params: { windowId: "w", groupId: "demo", command, args, ...(method === "app.execute" ? { requestId: "edit", expectedContext: registry.list()[0]!.contextToken } : {}) } });
  return { registry, request, remove, calls: () => calls, disable: () => { enabled = false; } };
}
test("discovery publishes strict schemas, availability and context; writes acknowledge, queries observe", async () => {
  const f = fixture(); const before = f.registry.list()[0]!;
  assert.equal(before.commands[1]!.inputSchema.additionalProperties, false);
  const result = await f.registry.execute(f.request("set", { value: 3 }), "w");
  assert.equal(result.state, "applied"); assert.equal(result.readiness, "command-acknowledged");
  assert.notEqual(result.contextToken, before.contextToken); assert.deepEqual(result.snapshot, { value: 3 });
  assert.equal((await f.registry.execute(f.request("read", {}, "app.query"), "w")).output, 3);
});
test("stale context, invalid arguments, read-only and disabled actions cannot mutate", async () => {
  const f = fixture(); const stale = f.request("set", { value: 5 });
  await f.registry.execute(f.request("set", { value: 1 }), "w");
  assert.equal((await f.registry.execute(stale, "w")).message, "CONTEXT_CONFLICT");
  for (const args of [{ value: "2" }, { value: 2, extra: true }, { value: Infinity }]) {
    const result = await f.registry.execute(f.request("set", args), "w");
    assert.equal(result.readiness, "not-applied");
  }
  assert.equal((await f.registry.execute(f.request("set", { value: 8 }, "app.query"), "w")).message, "READ_ONLY_REQUIRED");
  assert.equal((await f.registry.execute(f.request("read"), "w")).message, "READ_ONLY_COMMAND");
  f.disable(); assert.equal((await f.registry.execute(f.request("set", { value: 8 }), "w")).message, "COMMAND_DISABLED");
  assert.equal(f.calls(), 1);
});
test("window/request identity and group lifetime are guarded", async () => {
  const f = fixture();
  assert.equal((await f.registry.execute({ id: "r", method: "app.commands", params: { windowId: "other" } }, "w")).message, "TARGET_MISMATCH");
  assert.equal((await f.registry.execute({ ...f.request("set", { value: 5 }), id: "wrong" }, "w")).message, "TARGET_MISMATCH");
  f.remove(); assert.equal((await f.registry.execute(f.request("read", {}, "app.query"), "w")).message, "GROUP_UNAVAILABLE");
});
test("normal mutations serialize while explicit cancellation and observation can proceed", async () => {
  const registry = new AppCommandRegistry(); let release!: () => void; let cancelled = 0;
  registry.register({ id: "job", title: "Job", context: () => 0, snapshot: () => ({ cancelled }), commands: [
    command("start", "Start", empty, () => new Promise<void>((resolve) => { release = resolve; })),
    command("cancel", "Cancel", empty, () => { cancelled++; release(); }, { interrupt: true }),
  ] });
  const req = (name: string): ControlRequest => ({ id: name, method: "app.execute", params: { windowId: "w", groupId: "job", command: name, requestId: name, expectedContext: registry.list()[0]!.contextToken } });
  const pending = registry.execute(req("start"), "w");
  assert.equal((await registry.execute(req("start"), "w")).message, "CONTROL_BUSY");
  assert.equal((await registry.execute({ id: "q", method: "app.query", params: { windowId: "w", groupId: "job", command: "inspect" } }, "w")).state, "ready");
  assert.equal((await registry.execute(req("cancel"), "w")).state, "applied");
  assert.equal((await pending).state, "applied"); assert.equal(cancelled, 1);
});
test("errors after entering an executor retain an unknown outcome, without retry", async () => {
  const registry = new AppCommandRegistry(); let calls = 0;
  registry.register({ id: "x", title: "X", context: () => 0, snapshot: () => 0, commands: [command("partial", "Partial", empty, () => { calls++; throw new Error("AFTER_EFFECT"); })] });
  const result = await registry.execute({ id: "e", method: "app.execute", params: { windowId: "w", groupId: "x", command: "partial", requestId: "e", expectedContext: registry.list()[0]!.contextToken } }, "w");
  assert.equal(result.code, "OUTCOME_UNKNOWN"); assert.equal(result.readiness, "unverified"); assert.equal(calls, 1);
});
test("unmounted/replaced targets cannot report verified state", async () => {
  const registry = new AppCommandRegistry();
  const remove = registry.register({ id: "x", title: "X", context: () => 0, snapshot: () => 0, commands: [command("close", "Close", empty, () => remove())] });
  const result = await registry.execute({ id: "e", method: "app.execute", params: { windowId: "w", groupId: "x", command: "close", requestId: "e", expectedContext: registry.list()[0]!.contextToken } }, "w");
  assert.equal(result.state, "applied"); assert.equal(result.code, "TARGET_UNMOUNTED"); assert.equal(result.readiness, "unverified");
});
test("JSON values reject prototype keys and excessive nesting", () => {
  assert.throws(() => record.parse(JSON.parse('{"__proto__":{"polluted":true}}')));
  let value: unknown = 0; for (let i = 0; i < 18; i++) value = { child: value };
  assert.throws(() => record.parse(value));
});

test("edit permission does not imply plugin trust or live execution; direct execution checks the required scope", async () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window");
  const bridge = { controlScopes: ["observe", "app.edit"] };
  Object.defineProperty(globalThis, "window", { configurable: true, value: { candlescopeDesktop: bridge } });
  try {
    const registry = new AppCommandRegistry(); let calls = 0;
    registry.register({ id: "privileged", title: "Privileged", context: () => 0, snapshot: () => ({ calls }), commands: [
      command("trust", "Grant trust", empty, () => calls++, { requiredScope: "app.trust" }),
      command("live", "Execute live", empty, () => calls++, { requiredScope: "app.live" }),
    ] });
    const request = (name: string): ControlRequest => ({ id: name, method: "app.execute", params: { windowId: "w", groupId: "privileged", command: name, args: {}, requestId: name, expectedContext: registry.list()[0]!.contextToken } });
    for (const name of ["trust", "live"]) assert.equal((await registry.execute(request(name), "w")).message, "COMMAND_DISABLED");
    assert.equal(calls, 0);
    bridge.controlScopes.push("app.trust"); assert.equal((await registry.execute(request("trust"), "w")).state, "applied");
    assert.equal((await registry.execute(request("live"), "w")).message, "COMMAND_DISABLED"); assert.equal(calls, 1);
  } finally { if (previous) Object.defineProperty(globalThis, "window", previous); else Reflect.deleteProperty(globalThis, "window"); }
});

test("large immutable input replacements invalidate context without scanning the payload", () => {
  const payload = { get rows(): unknown { throw new Error("Must not traverse"); } };
  assert.equal(contextReference(payload), contextReference(payload));
  assert.notEqual(contextReference(payload), contextReference({ rows: [] }));
  assert.equal(contextReference(null), null);
});

test("reactive proxies become JSON data; a non-data result preserves an applied write", async () => {
  const registry = new AppCommandRegistry();
  registry.register({ id: "json", title: "JSON", context: () => 0, snapshot: () => new Proxy({ value: 2 }, {}), commands: [
    command("data", "Data", empty, () => new Proxy({ ok: true }, {}), { readOnly: true }),
    command("bad", "Bad result", empty, () => ({ callback: () => {} })),
  ] });
  const query = await registry.execute({ id: "q", method: "app.query", params: { windowId: "w", groupId: "json", command: "data" } }, "w");
  assert.deepEqual(structuredClone(query), { state: "ready", readiness: "observed", contextToken: registry.list()[0]!.contextToken, output: { ok: true }, snapshot: { value: 2 } });
  const mutation = await registry.execute({ id: "e", method: "app.execute", params: { windowId: "w", groupId: "json", command: "bad", requestId: "e", expectedContext: registry.list()[0]!.contextToken } }, "w");
  assert.equal(mutation.state, "applied"); assert.equal(mutation.code, "RESULT_UNAVAILABLE"); assert.equal(mutation.readiness, "unverified");
});
