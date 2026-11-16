import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ExtensionManager, { ExtensionRecovery } from "../ExtensionManager.js";
import { setLocale } from "../../../i18n/index.js";
import { LOCALES as lazyTestLocales, loadLocaleCatalog } from "../../../i18n/registry.js";
import { recoveryNotice } from "../recoveryNotice.js";

test.before(async () => { await Promise.all(lazyTestLocales.map(loadLocaleCatalog)); });

test("the recovery notice appears only after a failure or in recovery mode", () => {
  setLocale("en");
  assert.equal(recoveryNotice({ errors: {}, safeMode: false }, false), null);
  // A registry read failure is usually a brief outage of the local service; management still shows it.
  assert.equal(recoveryNotice({ errors: { runtime: "Error: offline" }, safeMode: false }, false), null);
  assert.deepEqual(recoveryNotice({ errors: { "b.second": "x", "a.first": "y", runtime: "z" }, safeMode: false }, false),
    { tone: "warning", title: "An extension failed to load", message: "a.first, b.second" });
  assert.equal(recoveryNotice({ errors: {}, safeMode: true }, false)?.tone, "info");
  assert.equal(recoveryNotice({ errors: { "a.first": "y" }, safeMode: false }, true)?.title, "Recovery mode: extensions are not running");
});

test("nothing about extensions is on screen while they are healthy", () => {
  // The always-visible recovery chip is gone; the recovery dialog renders only when opened.
  assert.equal(renderToStaticMarkup(<ExtensionRecovery />), "");
});

test("extension management keeps the names the desktop qualification drives", () => {
  const html = renderToStaticMarkup(<ExtensionManager />);
  assert.match(html, /<section class="extension-manager"/);
  assert.match(html, /<h3>(可信扩展|Trusted extensions)<\/h3>/);
  // The package picker is a labelled file input, not the browser's untranslated "Choose file" control.
  assert.match(html, /<label for="[^"]+" class="ui-file-drop ui-file-drop-compact"/);
  assert.match(html, /class="ui-file-drop-label">(导入扩展包|Import extension package)</);
  assert.match(html, />(不加载扩展并刷新|Reload without extensions)</);
});

test("extension management speaks every language from the catalogs, not only Chinese and English", () => {
  setLocale("de");
  const html = renderToStaticMarkup(<ExtensionManager />);
  assert.match(html, /Vertrauenswürdige Erweiterungen/);
  assert.match(html, /Erweiterungspaket importieren/);
  setLocale("zh-CN");
});
