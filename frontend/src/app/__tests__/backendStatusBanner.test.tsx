import { loadLocaleCatalog } from "../../i18n/registry.js";
import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import BackendStatusBanner from "../BackendStatusBanner.js";
import type { BackendConnectionState, BackendConnectionStore } from "../../desktop/backendConnection.js";
import { getLocale, setLocale } from "../../i18n/index.js";

test.before(async () => { await Promise.all((["en", "zh-CN"] as const).map(loadLocaleCatalog)); });

function storeFor(state: Partial<BackendConnectionState>): BackendConnectionStore {
  const snapshot: BackendConnectionState = {
    phase: "running", generation: 1, attempt: 0, maxAttempts: 3, retryAt: null, error: null, ...state,
  };
  return { supervised: true, getSnapshot: () => snapshot, subscribe: () => () => undefined, restart: async () => undefined };
}

function render(locale: string, state: Partial<BackendConnectionState>): string {
  const previous = getLocale();
  setLocale(locale);
  try {
    return renderToStaticMarkup(<BackendStatusBanner store={storeFor(state)} />);
  } finally {
    setLocale(previous);
  }
}

test("nothing is shown while the local service is running", () => {
  assert.equal(render("en", { phase: "running" }), "");
});

test("an automatic restart says which try it is and that data is not live", () => {
  const html = render("en", { phase: "restarting", attempt: 2 });
  assert.match(html, /data-backend-phase="restarting"/);
  assert.match(html, /role="status"/);
  assert.match(html, /The local service stopped unexpectedly\. Restarting \(try 2 of 3\)…/);
  assert.match(html, /Charts and prices aren(&#x27;|')t live until it(&#x27;|')s back\./);
  assert.doesNotMatch(html, /data-backend-restart/, "no button while it is restarting by itself");
  assert.match(render("en", { phase: "restarting", attempt: 0 }), /Restarting the local service…/);
});

test("after the tries run out, the banner offers an explicit restart with the reason", () => {
  const html = render("en", { phase: "failed", attempt: 3, error: "Sidecar health check timed out" });
  assert.match(html, /role="alert"/);
  assert.match(html, /The local service stopped and couldn(&#x27;|')t be restarted/);
  assert.match(html, /<button[^>]*data-backend-restart="true"[^>]*>Restart local service<\/button>/);
  assert.match(html, /Reason: Sidecar health check timed out/);
  assert.match(render("en", { phase: "stopped" }), /The local service is stopped[\s\S]*Restart local service/);
});

test("the banner is translated", () => {
  const html = render("zh-CN", { phase: "failed", attempt: 3 });
  assert.match(html, /本地服务已停止，未能自动重启/);
  assert.match(html, /服务恢复前，图表和价格不是实时数据。/);
  assert.match(html, />重启本地服务</);
  assert.match(render("zh-CN", { phase: "restarting", attempt: 1 }), /第 1 次，共 3 次/);
});
