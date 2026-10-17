import assert from "node:assert/strict";
import test, { mock } from "node:test";
import { createBacktestApi } from "../backtestApi.js";

test("external provider control uses scoped paths, bounded trace pagination, abort signals and no credential header", async () => {
  const captured: Array<{ url: string; init?: RequestInit }> = [];
  const stub = mock.method(globalThis, "fetch", async (input: string | URL | Request, init?: RequestInit) => {
    captured.push({ url: String(input), ...(init ? { init } : {}) });
    return Response.json({ connections: [], manifest: {}, manifest_command: "python --manifest", connection_id: "epc_one",
      items: [], next_after: 7, has_more: false });
  });
  try {
    const api = createBacktestApi("/external-wire").externalProviders!;
    const controller = new AbortController();
    const source = { strategy_revision_id: "srv_one", dataset_id: "data_one", data_epoch: "epoch_one", snapshot_hash: "snapshot_one" };
    await api.example(controller.signal);
    assert.deepEqual(await api.list(controller.signal), []);
    await api.create(source, controller.signal);
    await api.smoke("epc/ one", { ...source, parameters: { quantity: "0.001" } }, controller.signal);
    await api.revoke("epc/ one", controller.signal);
    assert.equal((await api.trace("run/ one", 7, controller.signal)).next_after, 7);
    assert.deepEqual(captured.map(({ url, init }) => [init?.method ?? "GET", url]), [
      ["GET", "/external-wire/provider-connections/example"], ["GET", "/external-wire/provider-connections"],
      ["POST", "/external-wire/provider-connections"], ["POST", "/external-wire/provider-connections/epc%2F%20one/smoke"],
      ["POST", "/external-wire/provider-connections/epc%2F%20one/revoke"],
      ["GET", "/external-wire/provider-connections/runs/run%2F%20one/trace?after=7&limit=200"],
    ]);
    assert.deepEqual(JSON.parse(String(captured[2]?.init?.body)), source);
    for (const { init } of captured) {
      assert.equal(init?.signal, controller.signal);
      assert.equal(new Headers(init?.headers).has("Authorization"), false);
    }
  } finally { stub.mock.restore(); }
});
