import test from "node:test";
import assert from "node:assert/strict";
import { LocalMcpHost } from "./local-mcp-host.mjs";

test("access starts disabled, rotates, revokes and is never restored by a new host", async (t) => {
  const host = new LocalMcpHost(); t.after(() => host.close());
  assert.equal(host.status().mode, "off"); assert.equal(host.status().token, null);
  const first = await host.setMode("read");
  const second = await host.setMode("control"); assert.notEqual(first.token, second.token);
  await assert.rejects(fetch(first.endpoint));
  assert.equal((await fetch(second.endpoint, { headers: { Authorization: `Bearer ${first.token}` } })).status, 401);
  assert.equal((await host.setMode("off")).endpoint, null); await assert.rejects(fetch(second.endpoint));
  assert.equal(new LocalMcpHost().status().mode, "off");
});

test("concurrent permission changes serialize and leave no orphan listener", async (t) => {
  const host = new LocalMcpHost(); t.after(() => host.close());
  const [one, two, off] = await Promise.all([host.setMode("control"), host.setMode("read"), host.setMode("off")]);
  assert.equal(off.mode, "off"); await assert.rejects(fetch(one.endpoint)); await assert.rejects(fetch(two.endpoint));
  await assert.rejects(host.setMode("admin"), /INVALID_CONTROL_MODE/);
});
