import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createExtensionContext } from "../runtime.js";
import { getExtensionState, publishExtensions, getHostService } from "../state.js";
import { getPaneThemeColors } from "../../../chart-adapter/chartPaneLifecycle.js";
import MarketPageFrame from "../../../app/MarketPageFrame.js";

const record = (id: string) => ({ manifest: {
  schema: "candlescope.extension/1" as const, id, name: id, version: "1.0.0", apiVersion: 1 as const, trust: "full-trust" as const,
}, digest: "a".repeat(64), generation: 1, enabled: true, history: [], error: null });

test("registered contributions clean up even when another cleanup throws", async () => {
  const owned = createExtensionContext(record("example.test"));
  owned.context.commands.register("ping", (payload) => payload);
  owned.context.services.register("probe", 42);
  owned.context.ui.replaceSlot("topBar", ({ fallback }) => <div>{fallback}</div>);
  let received = 0;
  owned.context.events.on("probe", () => { received++; });
  owned.context.events.emit("probe", null);
  assert.equal(received, 1);
  assert.equal(owned.context.commands.execute("example.test.ping", "hello"), "hello");
  assert.equal(getHostService("example.test.probe"), 42);
  owned.context.track(() => { throw new Error("cleanup failure"); });
  await assert.rejects(async () => owned.dispose(), /Failed to dispose/);
  assert.equal(getExtensionState().slots.size, 0);
  assert.throws(() => getHostService("example.test.probe"), /not mounted/);
  assert.throws(() => owned.context.commands.execute("example.test.ping"), /unavailable/);
  owned.context.events.emit("probe", null);
  assert.equal(received, 1);
});

test("replacement conflict cannot silently overwrite another extension", async () => {
  const first = createExtensionContext(record("example.first"));
  const second = createExtensionContext(record("example.second"));
  first.context.ui.replaceSlot("statusBar", () => <span>First</span>);
  assert.throws(() => second.context.ui.replaceSlot("statusBar", () => null), /already replaced/);
  await second.dispose();
  assert.equal(getExtensionState().slots.has("statusBar"), true);
  await first.dispose();
});

test("selected theme reaches chart canvas and removal restores ordinary appearance", () => {
  publishExtensions({ theme: { base: "light", tokens: { "bg-primary": "#fefefe", "text-secondary": "#123456", "border-color": "#dddddd" } } });
  assert.deepEqual(getPaneThemeColors({ theme: "dark" }), { bgColor: "#fefefe", textColor: "#123456", gridColor: "#dddddd", borderColor: "#dddddd" });
  publishExtensions({ theme: { base: "light", tokens: { "accent-blue": "#112233" } } });
  assert.equal(getPaneThemeColors({ theme: "dark" }).bgColor, "#ffffff");
  assert.equal(getPaneThemeColors({ theme: "dark" }).textColor, "#1e293b");
  publishExtensions({ theme: null });
  assert.equal(getPaneThemeColors({ theme: "light" }).bgColor, "#ffffff");
});

test("page layout reorders supplied host slots without dropping them", () => {
  publishExtensions({ layout: { page: ["statusBar", "workspace", "topBar", "intervalSelector", "featureSurfaces"], workspace: [] } });
  const html = renderToStaticMarkup(<MarketPageFrame topBar={<b>TOP</b>} intervalSelector={<b>INTERVAL</b>} workspace={<b>CHART</b>} featureSurfaces={<b>FEATURES</b>} statusBar={<b>STATUS</b>} />);
  assert.ok(html.indexOf("STATUS") < html.indexOf("CHART"));
  for (const text of ["TOP", "INTERVAL", "CHART", "FEATURES", "STATUS"]) assert.equal(html.split(text).length, 2);
  publishExtensions({ layout: null });
});
