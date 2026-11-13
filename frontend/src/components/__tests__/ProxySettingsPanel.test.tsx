import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import ProxySettingsPanel, { type ProxySettingsPanelProps } from "../settings/ProxySettingsPanel.js";

function panel(overrides: Partial<ProxySettingsPanelProps> = {}) {
  return renderToStaticMarkup(<ProxySettingsPanel
    proxyMode="custom" customProxy="http://127.0.0.1:7890" systemProxy="" effectiveProxy=""
    proxyLoading={false} proxyTestResult={null} proxySaveMsg={null}
    onProxyModeChange={() => undefined} onCustomProxyChange={() => undefined}
    onProxyTest={() => undefined} onProxySave={() => undefined}
    {...overrides} />);
}

test("the proxy can be saved only when it has unsaved edits, and says so", () => {
  const saved = panel();
  assert.match(saved, /<button[^>]*disabled=""[^>]*>保存代理<\/button>/, "nothing to save");
  assert.doesNotMatch(saved, /有未保存的更改/);
  const edited = panel({ proxyDirty: true });
  assert.doesNotMatch(edited, /<button[^>]*disabled=""[^>]*>保存代理<\/button>/);
  assert.match(edited, /有未保存的更改/);
});

test("the proxy form uses the kit: a labelled address field and the mode cards as toggles", () => {
  const html = panel();
  assert.match(html, /<label class="ui-field-label"[^>]*>代理地址<\/label>/);
  assert.match(html, /class="ui-input"[^>]*value="http:\/\/127.0.0.1:7890"/);
  assert.match(html, /aria-pressed="true"[^>]*>.*?自定义/);
  const system = panel({ proxyMode: "system", systemProxy: "" });
  assert.match(system, /class="ui-alert" data-tone="warning"/);
});

test("route diagnostics sit behind a disclosure", () => {
  const html = panel({
    proxyMode: "pool",
    proxyRoutes: [{ id: "a", name: "A", url: "", egress_group: "shared", enabled: true, exchanges: ["binance"], max_concurrency: 4 }],
  });
  assert.match(html, /<details class="ui-disclosure"[^>]*><summary[^>]*>.*?运行状态/);
});
