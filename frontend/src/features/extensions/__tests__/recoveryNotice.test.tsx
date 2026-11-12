import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ExtensionManager, { ExtensionRecovery } from "../ExtensionManager.js";
import { recoveryNotice } from "../recoveryNotice.js";

const en = (_zh: string, english: string) => english;

test("the recovery notice appears only after a failure or in recovery mode", () => {
  assert.equal(recoveryNotice({ errors: {}, safeMode: false }, false, en), null);
  // A registry read failure is usually a brief backend outage; management still shows it.
  assert.equal(recoveryNotice({ errors: { runtime: "Error: offline" }, safeMode: false }, false, en), null);
  assert.deepEqual(recoveryNotice({ errors: { "b.second": "x", "a.first": "y", runtime: "z" }, safeMode: false }, false, en),
    { tone: "warning", title: "An extension failed to load", message: "a.first, b.second" });
  assert.equal(recoveryNotice({ errors: {}, safeMode: true }, false, en)?.tone, "info");
  assert.equal(recoveryNotice({ errors: { "a.first": "y" }, safeMode: false }, true, en)?.title, "Recovery mode: extensions are not running");
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
