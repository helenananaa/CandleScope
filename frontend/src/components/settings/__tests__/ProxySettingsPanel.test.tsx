import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ProxySettingsPanel from "../ProxySettingsPanel.js";
import { getLocale, setLocale } from "../../../i18n/index.js";

test("network success does not label missing or uninitialized engine status as started", () => {
  const previous = getLocale();
  try {
    setLocale("en");
    for (const [status, expected] of [[undefined, "Unknown;"], ["not_initialized", "Not ready;"], ["ready", "Started"]] as const) {
      const html = renderToStaticMarkup(<ProxySettingsPanel proxyMode="none" customProxy="" systemProxy="" effectiveProxy="" proxyLoading={false} proxySaveMsg={null}
        proxyTestResult={{ success: true, message: "3/3 reachable", ...(status ? { data_engine: status } : {}) }}
        onProxyModeChange={() => {}} onCustomProxyChange={() => {}} onProxyTest={() => {}} onProxySave={() => {}} />);
      assert.ok(html.includes("3/3 reachable"));
      assert.ok(html.includes(expected));
      if (status !== "ready") assert.ok(!html.includes(">Started<"));
    }
  } finally { setLocale(previous); }
});

test("pool controls show exit grouping and cooldown without inventing websocket latency", () => {
  const previous = getLocale();
  try {
    setLocale("en");
    const html = renderToStaticMarkup(<ProxySettingsPanel proxyMode="pool" customProxy="" systemProxy="" effectiveProxy="" proxyLoading={false}
      proxySaveMsg={null} proxyTestResult={null} onProxyModeChange={() => {}} onCustomProxyChange={() => {}} onProxyTest={() => {}} onProxySave={() => {}}
      proxyRoutes={[{id:"a",name:"Primary",url:"http://user:secret@localhost:7890",egress_group:"shared",enabled:true,exchanges:[],max_concurrency:4}]}
      proxyStrategy="balanced" proxyPoolStatus={{routes:[{id:"a",active_requests:0,observations:[{exchange:"binance",kind:"ws",successes:0,failures:3,latency_ms:null,cooldown_seconds:5}],budgets:{}}]}}/>);
    assert.ok(html.includes("Exit group"));
    assert.ok(html.includes("Smart balancing"));
    assert.ok(html.includes("Waiting / cooldown: 5 s"));
    assert.ok(!html.includes("Latency: 250"));
    assert.ok(html.includes('type="password"'));
  } finally { setLocale(previous); }
});
