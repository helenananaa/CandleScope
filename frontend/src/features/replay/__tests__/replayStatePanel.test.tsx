import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReplayStatePanel from "../components/ReplayStatePanel.js";

type Runtime = React.ComponentProps<typeof ReplayStatePanel>["runtime"];
const recovering: Runtime = {
  phase: "ACTIVE", error: null,
  store: { hasAuthoritativeSnapshot: false, error: null },
  actions: { retry() {}, requestResync() {} },
};
const transportError = { code: "REPLAY_TRANSPORT_ERROR", message: "replay WebSocket transport error" };

test("failed resync shows the transport cause and a retry without an authoritative snapshot", () => {
  const html = renderToStaticMarkup(<ReplayStatePanel runtime={{ ...recovering,
    store: { hasAuthoritativeSnapshot: false, error: transportError } }} />);
  assert.match(html, /data-replay-state="error"/);
  assert.match(html, /REPLAY_TRANSPORT_ERROR/);
  assert.match(html, /replay WebSocket transport error/);
  assert.match(html, /data-replay-action="resync"/);
  assert.doesNotMatch(html, /replay-loading-spinner/);
});

test("initial connection and a resync awaiting a snapshot remain loading until an error arrives", () => {
  for (const phase of ["CONNECTING_SESSION", "ACTIVE"] as const) {
    const html = renderToStaticMarkup(<ReplayStatePanel runtime={{ ...recovering, phase }} />);
    assert.match(html, /data-replay-state="loading"/);
    assert.doesNotMatch(html, /data-replay-state="error"/);
  }
});

test("terminal runtime errors keep the capability retry and entry errors cannot retry an invalid route", () => {
  for (const phase of ["ERROR", "ENTRY_ERROR"] as const) {
    const html = renderToStaticMarkup(<ReplayStatePanel runtime={{ ...recovering, phase,
      error: { code: "REPLAY_ENTRY_INVALID", message: "invalid route" },
      store: { hasAuthoritativeSnapshot: false, error: transportError } }} />);
    assert.match(html, /REPLAY_ENTRY_INVALID/);
    assert.doesNotMatch(html, /REPLAY_TRANSPORT_ERROR/);
    assert.equal(html.includes('<button'), phase === "ERROR");
    assert.doesNotMatch(html, /data-replay-action="resync"/);
  }
});
