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
