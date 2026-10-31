import assert from "node:assert/strict";
import test from "node:test";
import { EventEmitter } from "node:events";
import { request as httpRequest } from "node:http";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { DesktopControlService } from "./control-service.mjs";
import { DESKTOP_IPC } from "./ipc-contract.mjs";

function fixture(options = {}) {
  const contents = new EventEmitter(); const window = new EventEmitter();
  let sent = 0;
  window.webContents = contents; window.isDestroyed = () => false;
  window.getContentBounds = () => ({ width: 1280, height: 720 });
  const manager = { windows: new Map([["main-window", window]]), options: {}, windowIdForContents: (sender) => sender === contents ? "main-window" : null };
  const service = new DesktopControlService({ manager, channels: DESKTOP_IPC, edit: true, ...options });
  contents.send = (_channel, payload) => { sent++; contents.emit("request", payload); };
  service.ready("main-window");
  return { service, contents, window, sent: () => sent };
}
const configuration = { requestId: "edit-1", workspaceId: "w", windowId: "main-window", expectedRevision: 0, charts: [] };

test("indicator sandbox navigation preserves workflow readiness and pending commands", async () => {
  const f = fixture();
  try {
    await f.service.call("workspace.configure", configuration);
    f.contents.emit("did-start-loading");
    f.contents.emit("did-start-navigation", {}, "about:srcdoc", false, false);
    f.contents.emit("did-start-navigation", {}, "http://127.0.0.1/index.html#chart", true, true);
    assert.equal(f.service.capabilities().windows[0].ready, true);
    assert.equal((await f.service.call("request.get", { requestId: "edit-1" })).final, false);
    f.service.acceptResult("main-window", { instanceId: f.service.instanceId, id: "edit-1", result: { state: "ready" }, final: true });
    await Promise.resolve();
    assert.equal((await f.service.call("request.get", { requestId: "edit-1" })).state, "ready");
  } finally { await f.service.close(); }
});

test("generic commands share the receipt ledger; cancellation can reach the renderer during an async action", async () => {
  const f = fixture();
  const params = { requestId: "command-1", windowId: "main-window", groupId: "job", command: "start", expectedContext: "context", args: {} };
  await f.service.call("app.execute", params);
  await f.service.call("app.execute", params); assert.equal(f.sent(), 1);
  await f.service.call("app.execute", { ...params, requestId: "command-cancel", command: "cancel" }); assert.equal(f.sent(), 2);
  await assert.rejects(f.service.call("workspace.configure", configuration), { code: "CONTROL_BUSY" });
  f.service.acceptResult("main-window", { instanceId: f.service.instanceId, id: params.requestId, result: { state: "applied" }, final: true });
  f.service.acceptResult("main-window", { instanceId: f.service.instanceId, id: "command-cancel", result: { state: "applied" }, final: true });
  assert.equal((await f.service.call("request.get", { requestId: params.requestId })).final, true);
  await f.service.close();
});

test("app pages use the existing managed-window authority and only fixed application paths", async () => {
  const f = fixture(); let opened;
  f.service.manager.options.appUrl = "http://127.0.0.1:1234/index.html";
  f.service.manager.openAppPage = async (url) => { opened = url; return { windowId: "app-1" }; };
  await f.service.call("app.open", { requestId: "open", windowId: "main-window", page: "strategy", search: "?native=1" });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(opened, "http://127.0.0.1:1234/strategy.html?native=1");
  assert.equal((await f.service.call("request.get", { requestId: "open" })).output.windowId, "app-1");
  await f.service.call("app.open", { requestId: "external", windowId: "main-window", page: "https://evil.example" });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal((await f.service.call("request.get", { requestId: "external" })).code, "INVALID_PARAMS");
  await f.service.close();
});

test("observation scope denies generic edits and page creation", async () => {
  const f = fixture({ edit: false });
  for (const method of ["app.execute", "app.open"]) await assert.rejects(f.service.call(method, { windowId: "main-window", requestId: "denied" }), { code: "SCOPE_DENIED" });
  assert.equal(f.sent(), 0); await f.service.close();
});

test("trust and live scopes require both edit permission and their explicit launch grant", async () => {
  for (const options of [{ edit: false, trust: true, live: true }, { edit: true }, { edit: true, trust: true, live: true }]) {
    const f = fixture(options); const scopes = f.service.capabilities().scopes;
    assert.equal(scopes.includes("app.trust"), options.edit && options.trust === true);
    assert.equal(scopes.includes("app.live"), options.edit && options.live === true);
    await f.service.close();
  }
});

test("duplicate mutation is executed once, conflicting retry is refused, progress is queryable", async () => {
  const f = fixture();
  const accepted = await f.service.call("workspace.configure", configuration);
  assert.equal(accepted.state, "accepted");
  await f.service.call("workspace.configure", configuration);
  assert.equal(f.sent(), 1);
  await assert.rejects(f.service.call("workspace.configure", { ...configuration, expectedRevision: 1 }), { code: "REQUEST_ID_CONFLICT" });
  f.service.acceptResult("other-window", { instanceId: f.service.instanceId, id: "edit-1", result: { state: "ready" }, final: true });
  assert.equal((await f.service.call("request.get", { requestId: "edit-1" })).state, "accepted");
  f.service.acceptResult("main-window", { instanceId: f.service.instanceId, id: "edit-1", result: { state: "applied", revision: 1 }, final: false });
  assert.equal((await f.service.call("request.get", { requestId: "edit-1" })).state, "applied");
  f.service.acceptResult("main-window", { instanceId: f.service.instanceId, id: "edit-1", result: { state: "ready", revision: 1 }, final: true });
  await Promise.resolve();
  const receipt = await f.service.call("request.get", { requestId: "edit-1" });
  assert.equal(receipt.final, true); assert.equal(receipt.state, "ready");
  await f.service.close();
});
test("observation grant excludes editing and session receipts are never evicted", async () => {
  const readOnly = fixture({ edit: false });
  await assert.rejects(readOnly.service.call("workspace.configure", configuration), { code: "SCOPE_DENIED" });
  assert.equal(readOnly.sent(), 0);
  await readOnly.service.close();
  const bounded = fixture({ maxRequests: 1 });
  await bounded.service.call("workspace.configure", configuration);
  bounded.service.acceptResult("main-window", { instanceId: bounded.service.instanceId, id: "edit-1", result: { state: "failed" }, final: true });
  await Promise.resolve();
  await assert.rejects(bounded.service.call("workspace.configure", { ...configuration, requestId: "edit-2" }), { code: "REQUEST_LIMIT" });
  await bounded.service.call("workspace.configure", configuration);
  assert.equal(bounded.sent(), 1);
  await bounded.service.close();
});
test("window reload and request timeout return an unknown mutation outcome without replay", async () => {
  const f = fixture({ requestTimeoutMs: 15 });
  await f.service.call("workspace.configure", configuration);
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal((await f.service.call("request.get", { requestId: "edit-1" })).code, "OUTCOME_UNKNOWN");
  await f.service.call("workspace.configure", configuration);
  assert.equal(f.sent(), 1);
  f.contents.emit("did-start-navigation", {}, "http://127.0.0.1/index.html", false, true);
  await assert.rejects(f.service.call("workspace.inspect", { windowId: "main-window" }), { code: "WINDOW_UNAVAILABLE" });
  await f.service.close();
});
test("renderer loss after application preserves the applied outcome", async () => {
  const f = fixture();
  await f.service.call("workspace.configure", configuration);
  f.service.acceptResult("main-window", { instanceId: f.service.instanceId, id: "edit-1", result: { state: "applied", revision: 1 }, final: false });
  f.contents.emit("did-start-navigation", {}, "http://127.0.0.1/index.html", false, true); await Promise.resolve();
  const receipt = await f.service.call("request.get", { requestId: "edit-1" });
  assert.equal(receipt.state, "applied"); assert.equal(receipt.readiness, "unverified");
  assert.equal(receipt.final, true); await f.service.close();
});
test("native capture bounds image size and returns PNG without renderer execution", async () => {
  const f = fixture({ edit: false });
  let captured = 0;
  f.contents.capturePage = async () => { captured++; return { getSize: () => ({ width: 1280, height: 720 }),
    resize: (size) => ({ toPNG: () => { assert.equal(size.width, 640); return Buffer.from("png"); } }) }; };
  assert.equal((await f.service.call("chart.capture", { windowId: "main-window", maxSide: 640 })).mimeType, "image/png");
  assert.equal(f.sent(), 0);
  f.window.getContentBounds = () => ({ width: 10000, height: 10000 });
  await assert.rejects(f.service.call("chart.capture", { windowId: "main-window" }), { code: "CAPTURE_LIMIT" });
  assert.equal(captured, 1); await f.service.close();
});
test("local HTTP requires a private credential, exact host, no browser origin and bounded requests", async (t) => {
  const f = fixture();
  const directory = await mkdtemp(path.join(os.tmpdir(), "candlescope-control-"));
  t.after(async () => { await f.service.close(); assert.ok(directory.startsWith(path.join(os.tmpdir(), "candlescope-control-"))); await rm(directory, { recursive: true, force: true }); });
  const file = await f.service.start(directory);
  const descriptor = JSON.parse(await readFile(file, "utf8"));
  const call = (headers = {}, body = JSON.stringify({ method: "app.capabilities", params: {} })) => fetch(`${descriptor.endpoint}/call`, {
    method: "POST", headers: { "Content-Type": "application/json", ...headers }, body,
  });
  assert.equal((await call()).status, 403);
  const auth = { Authorization: `Bearer ${descriptor.token}` };
  assert.equal((await call({ ...auth, Origin: descriptor.endpoint })).status, 403);
  const wrongHostStatus = await new Promise((resolve, reject) => {
    const request = httpRequest(`${descriptor.endpoint}/call`, { method: "POST", headers: { ...auth, Host: "evil.example" } },
      (response) => { response.resume(); resolve(response.statusCode); });
    request.on("error", reject); request.end();
  });
  assert.equal(wrongHostStatus, 403);
  const response = await call(auth); assert.equal(response.status, 200);
  assert.equal((await response.json()).result.instanceId, descriptor.instanceId);
  assert.equal((await call(auth, "x".repeat(65 * 1024))).status, 413);
  assert.equal((await call(auth, JSON.stringify({ method: "app.capabilities", params: { token: "no" } }))).status, 400);
  await f.service.close();
  await assert.rejects(readFile(file), { code: "ENOENT" });
});
