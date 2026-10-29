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

test("edited route capacity cannot display the saved route's runtime counters", () => {
  const previous = getLocale();
  try {
    setLocale("en");
    const saved = {id:"a",name:"Primary",url:"http://localhost:7890",egress_group:"shared",
      enabled:true,exchanges:[],max_concurrency:4,max_ws_subscriptions:64};
    const html = renderToStaticMarkup(<ProxySettingsPanel proxyMode="pool" customProxy="" systemProxy="" effectiveProxy="" proxyLoading={false}
      proxySaveMsg={null} proxyTestResult={null} onProxyModeChange={() => {}} onCustomProxyChange={() => {}} onProxyTest={() => {}} onProxySave={() => {}}
      proxyRoutes={[{...saved,max_ws_subscriptions:32}]} proxySavedRoutes={[saved]}
      proxyPoolStatus={{routes:[{id:"a",active_requests:0,ws_subscriptions:8,max_ws_subscriptions:64,ws_sessions:12,
        native_websockets:1,ccxt_physical_websockets:2,observations:[],budgets:{}}]}}/>);
    assert.ok(html.includes("Status reflects saved routes"));
    assert.ok(!html.includes("WebSocket subscriptions: 8 / 64"));
    assert.ok(!html.includes("Physical WebSockets: 3"));
  } finally { setLocale(previous); }
});

test("pool controls show exit grouping and cooldown without inventing websocket latency", () => {
  const previous = getLocale();
  try {
    setLocale("en");
    const html = renderToStaticMarkup(<ProxySettingsPanel proxyMode="pool" customProxy="" systemProxy="" effectiveProxy="" proxyLoading={false}
      proxySaveMsg={null} proxyTestResult={null} onProxyModeChange={() => {}} onCustomProxyChange={() => {}} onProxyTest={() => {}} onProxySave={() => {}}
      proxyRoutes={[{id:"a",name:"Primary",url:"http://user:secret@localhost:7890",egress_group:"shared",enabled:true,exchanges:[],max_concurrency:4}]}
      proxyStrategy="balanced" proxyPoolStatus={{routes:[{id:"a",active_requests:0,ws_subscriptions:8,ws_sessions:12,max_ws_subscriptions:64,
        native_websockets:1,ccxt_physical_websockets:2,ws_traffic:{window_seconds:30,messages_per_second:12.5,payload_bytes_per_second:2048,
          messages_total:375,payload_bytes_total:61440,disconnects_total:7,disconnects_recent:2,last_message_age_seconds:4.8,
          queue_size:8,queue_capacity:64,queue_pressure:0.125},
        observations:[{exchange:"binance",kind:"ws",successes:0,failures:3,latency_ms:null,cooldown_seconds:5},
          {exchange:"binance",kind:"archive:data.binance.vision",successes:2,failures:0,latency_ms:1500,cooldown_seconds:0}],budgets:{}}]}}/>);
    assert.ok(html.includes("Exit group"));
    assert.ok(html.includes("Smart balancing"));
    assert.ok(html.includes("Waiting / cooldown: 5 s"));
    assert.ok(!html.includes("Latency: 250"));
    assert.ok(html.includes('type="password"'));
    assert.ok(html.includes("WebSocket subscription capacity"));
    assert.ok(html.includes("WebSocket subscriptions: 8 / 64"));
    assert.ok(html.includes("WebSocket sessions: 12"));
    assert.ok(html.includes("Physical WebSockets: 3"));
    assert.ok(html.includes("Received: 12.5 messages/s · 2.0 KiB/s (30 s average)"));
    assert.ok(html.includes("Delivery queues: 8 / 64"));
    assert.ok(html.includes("Disconnects in the last 30 s: 2"));
    assert.ok(html.includes("Last received payload: 4 s ago"));
    assert.ok(html.includes("Payload bytes exclude network overhead"));
    assert.ok(html.includes("ZIP · data.binance.vision"));
  } finally { setLocale(previous); }
});
