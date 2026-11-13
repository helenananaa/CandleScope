import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { ExportSettings } from "../ExportPanel.js";
import ExportPreviewPanel from "../ExportPreviewPanel.js";
import { DEFAULT_EXPORT_OPTIONS } from "../exportService.js";
import type { ExportOptions } from "../exportTypes.js";

function settings(options: Partial<ExportOptions> = {}) {
  return renderToStaticMarkup(<ExportSettings options={{ ...DEFAULT_EXPORT_OPTIONS, ...options }} onOptionsChange={() => undefined}
    filename="candlescope-binance-spot-BTCUSDT-1h-chart.png" />);
}

test("scope, format and scale are segmented controls with the chosen option's description under them", () => {
  const html = settings();
  for (const choice of ["scope", "format", "scale"]) {
    assert.match(html, new RegExp(`data-export-choice="${choice}"><span class="ui-field-label">[^<]+</span><div role="radiogroup"`));
  }
  assert.match(html, /role="radio" aria-checked="true"[^>]*class="ui-segment" data-value="chart">整张图表/);
  assert.match(html, /<p class="ui-field-hint">包含主图和所有指标窗格<\/p>/);
  assert.match(html, /role="radio" aria-checked="true"[^>]*data-value="png">PNG/);
  assert.match(html, /role="radio" aria-checked="true"[^>]*data-value="2">2x/);
  assert.doesNotMatch(html, /export-option-card|export-segmented/, "no option cards");
});

test("options are kit checkboxes and the full file name sits under its prefix, once", () => {
  const html = settings();
  for (const option of ["include-context", "hide-drawings", "watermark-enabled"]) {
    assert.match(html, new RegExp(`<label class="ui-check"><input type="checkbox" class="ui-check-input"[^>]*data-export-option="${option}"`));
  }
  assert.match(html, /<select[^>]*data-export-option="background"[^>]*class="ui-input ui-select"|<select[^>]*class="ui-input ui-select"[^>]*data-export-option="background"/);
  assert.equal((html.match(/candlescope-binance-spot-BTCUSDT-1h-chart\.png/g) ?? []).length, 1);
  assert.match(html, /<span class="export-filename">/);
});

test("JPEG shows a labelled quality slider and cannot be transparent", () => {
  const html = settings({ format: "jpeg" });
  assert.match(html, /<label class="ui-field-label" for="([^"]+)">图片质量：92%<\/label><input id="\1" type="range"/);
  assert.match(html, /<option value="transparent" disabled="">/);
});

test("the preview states its status and details on one line, with zoom and refresh beside them", () => {
  const html = renderToStaticMarkup(<ExportPreviewPanel previewUrl="blob:preview" filename="a.png" width={2006} height={1688}
    mimeType="image/png" generatedAt={Date.UTC(2026, 10, 14, 3, 1, 13)} isCurrent />);
  assert.match(html, /<span class="export-preview-status" data-tone="success">保存即此图<\/span><span>PNG<\/span><span>2006 × 1688<\/span>/);
  assert.match(html, /role="radiogroup" aria-label="预览缩放"/);
  assert.match(html, /class="ui-icon-btn ui-icon-btn-sm ui-icon-btn-secondary export-preview-refresh"[^>]*aria-label="重新生成当前预览"/);
  assert.doesNotMatch(html, /export-preview-meta-grid|style="/);
});

test("a failed preview is an alert with 重新生成", () => {
  const html = renderToStaticMarkup(<ExportPreviewPanel error="超时" onRefresh={() => undefined} />);
  assert.match(html, /class="ui-alert export-preview-error" data-tone="danger" role="alert">.*预览生成失败.*超时.*重新生成/s);
});
