import assert from "node:assert/strict";
import test from "node:test";
import { LocalControlBroker } from "./local-control-broker.mjs";

const view = { viewId: "chart-1", revision: "generation-1:4", kind: "market" };
const args = { windowId: "window-1", viewId: view.viewId, expectedRevision: view.revision, operationId: "op-1", interval: "5m" };

test("explicit target ownership, fresh revisions and receipts", async () => {
  const broker = new LocalControlBroker(); const sent = [];
  broker.register("window-1", (message) => sent.push(message)); broker.publish("window-1", [view]);
  broker.register("window-2", () => assert.fail("wrong window")); broker.publish("window-2", [view]);
  const pending = broker.invoke("candlescope_set_chart", args, new AbortController().signal);
  assert.equal(sent.length, 1);
  assert.equal(broker.reply("window-2", { requestId: sent[0].requestId, ok: true, result: {} }), false);
  await assert.rejects(broker.invoke("candlescope_set_chart", args, new AbortController().signal), /WINDOW_BUSY/);
  broker.reply("window-1", { requestId: sent[0].requestId, ok: true, result: { revision: "generation-1:5", interval: "5m" } });
  assert.deepEqual(await pending, { revision: "generation-1:5", interval: "5m" });
  await assert.rejects(broker.invoke("candlescope_set_chart", { ...args, expectedRevision: "wrong" }, new AbortController().signal), /REVISION_CONFLICT/);
  await assert.rejects(broker.invoke("candlescope_set_chart", { ...args, viewId: "missing" }, new AbortController().signal), /VIEW_NOT_FOUND/);
});

test("navigation closes pending requests and stale catalogs", async () => {
  const broker = new LocalControlBroker(); broker.register("window-1", () => {}); broker.publish("window-1", [view]);
  const pending = broker.invoke("candlescope_read_view", args, new AbortController().signal);
  broker.remove("window-1");
  await assert.rejects(pending, /WINDOW_CLOSED/); assert.deepEqual(broker.list(), { views: [] });
});

test("cancel never reports rollback of an admitted mutation", async () => {
  const broker = new LocalControlBroker(); const sent = []; broker.register("window-1", (message) => sent.push(message)); broker.publish("window-1", [view]);
  const controller = new AbortController(); const pending = broker.invoke("candlescope_set_chart", args, controller.signal);
  controller.abort(); await assert.rejects(pending, /OUTCOME_UNKNOWN_READ_VIEW/);
  assert.equal(sent[1].type, "cancel");
  assert.equal(broker.reply("window-1", { requestId: sent[0].requestId, ok: true, result: {} }), false);
  assert.equal(broker.pending.size, 0);
});

test("catalog exposes only bounded identity metadata", () => {
  const broker = new LocalControlBroker(); broker.register("window-1", () => {});
  broker.publish("window-1", [{ ...view, secret: "not published", price: 42 }]);
  assert.deepEqual(broker.list().views, [{ windowId: "window-1", ...view }]);
  assert.throws(() => broker.publish("window-1", [view, view]), /INVALID_CONTROL_VIEW/);
  assert.throws(() => broker.publish("window-1", [{ ...view, revision: "invalid whitespace" }]), /INVALID_CONTROL_VIEW/);
});
