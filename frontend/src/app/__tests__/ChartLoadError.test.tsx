import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ChartLoadError } from "../ChartLoadError.js";

test("load failures expose the original diagnostic as safe selectable text without a development command", () => {
  const html = renderToStaticMarkup(<ChartLoadError error={'DataManager not initialized <script>alert(1)</script>'} onRetry={() => {}} />);
  assert.match(html, /<details/);
  assert.match(html, /DataManager not initialized &lt;script&gt;/);
  assert.doesNotMatch(html, /<script>|--reload/);
  assert.match(html, /id="retry-btn"/);
});
