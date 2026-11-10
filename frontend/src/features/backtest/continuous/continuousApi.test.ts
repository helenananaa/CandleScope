import assert from "node:assert/strict";
import test from "node:test";
import { createContinuousApi } from "./continuousApi.js";
import type { CommittedIdentity, ContinuousCreate, ContinuousPacket } from "./continuousTypes.js";

test("HTTP creation preserves current code and a stable request key; bounded reads expose typed server errors", async (t) => {
  const original = globalThis.fetch; t.after(() => { globalThis.fetch = original; });
  const signal = new AbortController().signal;
  const api = createContinuousApi("http://127.0.0.1:8000/api/v1/backtests/continuous");
  globalThis.fetch = async (url, init) => {
    assert.equal(String(url).endsWith("/runs"), true); assert.equal(init!.signal, signal);
    assert.equal((init!.headers as Record<string, string>)["Idempotency-Key"], "chart/stable");
    const value = JSON.parse(String(init!.body)) as { mode: string; provider: { source_text: string } }; assert.equal(value.mode, "LIVE_ONLY");
    assert.equal(value.provider.source_text, "current editor code"); assert.equal("strategy_revision_id" in value, false);
    return new Response(JSON.stringify({ creation: { run_id: "one" } }), { status: 202 });
  };
  assert.equal((await api.create("chart/stable", { mode: "LIVE_ONLY", provider: { source_text: "current editor code" } } as ContinuousCreate, signal)).creation.run_id, "one");
  globalThis.fetch = async () => new Response(JSON.stringify({ error: { code: "CONTINUOUS_COMMIT_CONFLICT", message: "changed" } }), { status: 409 });
  await assert.rejects(api.initial("one", signal), { code: "CONTINUOUS_COMMIT_CONFLICT" });
  globalThis.fetch = async () => new Response("x".repeat(1024 * 1024 + 1));
  await assert.rejects(api.initial("one", signal), { code: "BUDGET_EXCEEDED" });
});

test("repair transport binds exact consent and stable request identity without editor source", async (t) => {
  const original = globalThis.fetch; t.after(() => { globalThis.fetch = original; });
  const api = createContinuousApi("http://local.test/continuous"), signal = new AbortController().signal;
  const requests: Array<{ url: string; init: RequestInit }> = [];
  globalThis.fetch = async (url, init) => { requests.push({ url: String(url), init: init! }); return new Response("{}"); };
  await api.repairPreview("one", { expected: after, resume_after: false }, signal);
  await api.repair("one", "repair/stable", { expected: after, plan_id: "a".repeat(64), resume_after: false, confirmed: true }, signal);
  await api.repairStatus("repair/stable", signal);
  await api.cancelRepair("repair/stable", after, signal);
  assert.equal(requests[0]!.url, "http://local.test/continuous/runs/one/repair/preview");
  assert.equal(requests[1]!.url, "http://local.test/continuous/runs/one/repairs");
  assert.equal((requests[1]!.init.headers as Record<string, string>)["Idempotency-Key"], "repair/stable");
  assert.deepEqual(JSON.parse(String(requests[1]!.init.body)), { expected: after, plan_id: "a".repeat(64), resume_after: false, confirmed: true });
  assert.equal(requests[2]!.url, "http://local.test/continuous/repairs/repair%2Fstable");
  assert.equal(requests[3]!.url, "http://local.test/continuous/repairs/repair%2Fstable/cancel");
  assert.deepEqual(JSON.parse(String(requests[3]!.init.body)), { expected: after });
});

class Socket {
  static latest: Socket;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  constructor(readonly url: URL) { Socket.latest = this; }
  close() { this.closed = true; }
}
function sockets(t: { after(fn: () => void): void }) {
  const original = globalThis.WebSocket;
  globalThis.WebSocket = Socket as unknown as typeof WebSocket;
  t.after(() => { globalThis.WebSocket = original; });
}
const after: CommittedIdentity = { id: "one", generation: 1, revision: 1, checkpoint_revision: 1, sequence: 1, event_time_ms: 60000, data_revision: "source" };

test("WebSocket resumes the complete identity, announces connection and releases on terminal result", async (t) => {
  sockets(t); const api = createContinuousApi("https://local.test/api/v1/backtests/continuous");
  const accepted: ContinuousPacket[] = [];
  const result = api.stream("one", after, new AbortController().signal, (value) => accepted.push(value));
  const socket = Socket.latest;
  assert.equal(socket.url.protocol, "wss:"); assert.equal(socket.url.searchParams.get("protocol"), "continuous.v1");
  assert.deepEqual(JSON.parse(socket.url.searchParams.get("after")!), after);
  socket.onopen!(); assert.equal(accepted[0]!.type, "connected");
  socket.onmessage!({ data: JSON.stringify({ protocol: "continuous.v1", type: "preparation", terminal: true }) });
  await result; assert.equal(socket.closed, true); assert.equal(socket.onmessage, null);
});

test("unsupported and over-budget socket messages fail before consumer publication", async (t) => {
  sockets(t); const api = createContinuousApi("http://local.test/continuous");
  for (const wire of [JSON.stringify({ protocol: "old", type: "snapshot" }), "x".repeat(1024 * 1024 + 1)]) {
    let accepted = 0;
    const result = api.stream("one", undefined, new AbortController().signal, () => { accepted += 1; });
    const rejected = assert.rejects(result, { code: wire[0] === "{" ? "PROTOCOL_UNSUPPORTED" : "BUDGET_EXCEEDED" });
    Socket.latest.onmessage!({ data: wire }); await rejected;
    assert.equal(accepted, 0); assert.equal(Socket.latest.closed, true);
  }
});

test("abort closes the view and network close requests bounded reconnect instead of restarting execution", async (t) => {
  sockets(t); const api = createContinuousApi("http://local.test/continuous"), controller = new AbortController();
  const result = api.stream("one", after, controller.signal, () => undefined);
  const rejected = assert.rejects(result, { name: "AbortError" }); controller.abort(); await rejected;
  assert.equal(Socket.latest.closed, true);
  const disconnected = api.stream("one", after, new AbortController().signal, () => undefined);
  const networkFailure = assert.rejects(disconnected, { code: "CONTINUOUS_DISCONNECTED" });
  Socket.latest.onclose!(); await networkFailure;
});
