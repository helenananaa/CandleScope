import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import DataSourcesSettingsPanel, { DataSourceSection } from "../DataSourcesSettingsPanel.js";
import type { DataSourceField, DataSourceStatus } from "../dataSourcesApi.js";
import { setLocale } from "../../../i18n/index.js";

function source(field: Partial<DataSourceField>): DataSourceStatus {
  return {
    id: "twelvedata", name: "Twelve Data", signupUrl: "https://twelvedata.com/pricing",
    fields: [{ id: "apiKey", saved: false, savedHint: null, savedAtMs: null, savedError: null,
      environmentVariable: "INGESTION_TWELVE_DATA_API_KEY", environmentSet: false, active: null, activeHint: null, ...field }],
  };
}

function render(value: DataSourceStatus, vaultAvailable = true) {
  setLocale("en");
  return renderToStaticMarkup(<DataSourceSection source={value} vaultAvailable={vaultAvailable} onStatus={() => undefined} />);
}

test("a saved key shows only its masked hint, with replace, test and remove", () => {
  const html = render(source({ saved: true, savedHint: "WXYZ", savedAtMs: 1_700_000_000_000, active: "saved", activeHint: "WXYZ" }));
  assert.match(html, /Using saved key/);
  assert.match(html, /••••WXYZ/);
  assert.match(html, /Replace/);
  assert.match(html, /Test connection/);
  assert.match(html, /Remove key/);
  assert.match(html, /type="password"/);
  assert.doesNotMatch(html, /value="[^"]+"/, "the key field starts empty");
});

test("the environment variable is named when it supplies the key, and nothing can be removed", () => {
  const html = render(source({ environmentSet: true, active: "environment", activeHint: "ENVK" }));
  assert.match(html, /Using environment variable/);
  assert.match(html, /INGESTION_TWELVE_DATA_API_KEY/);
  assert.match(html, /Set ••••ENVK/);
  assert.match(html, /Once you save a key here/);
  assert.doesNotMatch(html, /Remove key/);
});

test("a saved key that shadows the environment says which one is used", () => {
  const html = render(source({ saved: true, savedHint: "WXYZ", savedAtMs: 1, environmentSet: true, active: "saved", activeHint: "WXYZ" }));
  assert.match(html, /uses the one saved here/);
  assert.match(html, /Set ••••</, "the environment key's hint is not shown while the saved key is used");
});

test("no key: save only, testing is disabled", () => {
  const html = render(source({}));
  assert.match(html, /No key/);
  assert.match(html, /Paste your Twelve Data API key/);
  assert.match(html, /<button type="button" class="[^"]*" disabled="">Test connection/);
});

test("an unreadable saved key asks to save again; the code stays in technical details", () => {
  const html = render(source({ saved: true, savedHint: "WXYZ", savedAtMs: 1, savedError: "CREDENTIAL_NOT_FOUND" }));
  assert.match(html, /Save again/);
  assert.match(html, /couldn&#x27;t be read/);
  assert.match(html, /<details[^>]*>.*CREDENTIAL_NOT_FOUND/);
});

test("without a vault there is no key field", () => {
  const html = render(source({ environmentSet: true, active: "environment", activeHint: "ENVK" }), false);
  assert.doesNotMatch(html, /type="password"/);
  assert.match(html, /Test connection/);
});

test("outside the desktop app the panel says where to add keys", () => {
  setLocale("en");
  const html = renderToStaticMarkup(<DataSourcesSettingsPanel />);
  assert.match(html, /Add data source keys in the desktop app/);
});
