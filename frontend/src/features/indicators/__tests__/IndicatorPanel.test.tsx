import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import IndicatorEditor from "../IndicatorEditor.js";
import IndicatorPanel from "../IndicatorPanel.js";
import type { IndicatorPreset } from "../indicatorTypes.js";

function preset(id: string, name: string, description: string, paneTarget: string): IndicatorPreset {
  return {
    id, name, description, paneTarget, engineName: id.toUpperCase(), script: "", params: {}, category: "trend",
    paramSchema: [], outputs: [], is_builtin: true, isPreset: true, defaultEnabled: false,
  };
}

const presets = [
  preset("ma", "简单移动平均线 (SMA)", "Simple Moving Average", "main"),
  preset("rsi", "相对强弱指标 (RSI)", "Relative Strength Index", "new"),
];

function panel() {
  return renderToStaticMarkup(<IndicatorPanel isOpen onClose={() => undefined}
    staticCatalog={{ presets, resolvePresetForChart: (item) => item as IndicatorPreset }}
    activeIndicators={[{ ...presets[0]!, visible: true }]}
    onAddIndicator={() => undefined} onRemoveIndicator={() => undefined} onToggleVisibility={() => undefined}
    onUpdateParams={() => undefined} onUpdateScript={() => undefined} computing={false} />);
}

test("the indicator drawer has kit tabs, a kit create button and the shared resize handle", () => {
  const html = panel();
  assert.equal((html.match(/role="tab"/g) ?? []).length, 2);
  assert.match(html, /role="tab"[^>]*aria-selected="true"[^>]*>.*?指标库/s);
  assert.match(html, /<button[^>]*class="ui-btn[^"]*indicator-tab-create"/);
  assert.match(html, /class="right-drawer-resize-handle"/);
  assert.equal(html.match(/style="[^"]*"/g)?.join(" "), 'style="width:400px"', "only the drawer width is inline");
});

test("a library row is the name, one line of description and pane, and one add toggle", () => {
  const html = panel();
  assert.match(html, /<span class="indicator-row-desc">Simple Moving Average · 主图<\/span>/);
  assert.match(html, /<span class="indicator-row-desc">Relative Strength Index · 副图<\/span>/);
  assert.doesNotMatch(html, /内置|indicator-badge-/, "no 内置 or pane pills");
  assert.match(html, /data-indicator-id="ma"[^]*?aria-pressed="true"[^>]*aria-label="从图表移除"|data-indicator-id="ma"[^]*?aria-label="从图表移除"[^>]*aria-pressed="true"/);
  assert.match(html, /data-indicator-id="rsi"[^]*?aria-pressed="false"[^>]*aria-label="添加到图表"|data-indicator-id="rsi"[^]*?aria-label="添加到图表"[^>]*aria-pressed="false"/);
});

function editor(readOnly: boolean) {
  return renderToStaticMarkup(<IndicatorEditor readOnly={readOnly}
    indicator={{ id: null, name: "My Indicator", script: "//@version=6\nindicator(\"x\")", language: "pine", params: {} }}
    onSave={() => undefined} onBack={() => undefined} onPreview={() => undefined} onForkBuiltin={() => undefined}
    onToggleVisibility={() => undefined} />);
}

test("the editor toolbar holds its actions and a close button, with no inline styles", () => {
  const html = editor(false);
  assert.match(html, /class="indicator-editor-toolbar"/);
  assert.match(html, /class="ui-btn[^"]*indicator-editor-run"/);
  assert.match(html, /class="ui-btn ui-btn-primary[^"]*indicator-editor-save"/);
  assert.match(html, /aria-label="关闭编辑器"/);
  assert.doesNotMatch(html, /style="/);
  assert.match(html, /class="indicator-editor-console"[^>]*role="status"/);
});

test("advanced inputs are closed kit disclosures with labelled monospace text areas", () => {
  const html = editor(false);
  assert.match(html, /<div class="indicator-editor-advanced"><details class="ui-disclosure">/);
  assert.doesNotMatch(html, /<details[^>]*open/);
  assert.match(html, /<label class="ui-field-label" for="([^"]+)">宿主输入（JSON）<\/label><textarea class="ui-input ui-textarea indicator-editor-json"[^>]*id="\1"/);
  assert.match(html, /<label class="ui-check">.*?将收盘确认的 Pine 提醒发送到通知中心/s);
  assert.doesNotMatch(html, /text-transform|PINE SCRIPT/);
});

test("a built-in indicator opens read-only with 复制为自定义 as its one action", () => {
  const html = editor(true);
  assert.match(html, /<button[^>]*class="ui-btn ui-btn-primary[^"]*"[^>]*>复制为自定义<\/button>/);
  assert.doesNotMatch(html, /indicator-editor-run/);
  assert.match(html, /<input class="ui-input" readOnly=""/);
  assert.match(html, /aria-label="关闭编辑器"/);
});
