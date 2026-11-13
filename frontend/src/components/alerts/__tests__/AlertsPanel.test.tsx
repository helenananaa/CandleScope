import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import AlertsPanel from "../AlertsPanel.js";

function panel() {
  return renderToStaticMarkup(<AlertsPanel isOpen onClose={() => undefined}
    currentSymbol="BTCUSDT" currentMarketType="spot" currentExchange="binance" currentInterval="1h" displayPrice={69318.23} />);
}

test("the alerts drawer has kit tabs and no context card repeating the chart", () => {
  const html = panel();
  assert.match(html, /role="tablist"[^>]*aria-label="警报中心"/);
  assert.equal((html.match(/role="tab"/g) ?? []).length, 3);
  assert.doesNotMatch(html, /alert-context-card|实时状态/);
  assert.match(html, /className="right-drawer-resize-handle"|class="right-drawer-resize-handle"/);
});

test("the new alert form is numbered sections of kit fields, with the dry run folded away", () => {
  const html = panel();
  assert.match(html, /<section class="alert-step" aria-label="选择警报商品">/);
  assert.match(html, /<label class="ui-field-label"[^>]*>警报商品<\/label>/);
  assert.match(html, /<select[^>]*class="ui-input ui-select"/);
  assert.doesNotMatch(html, /alert-editor-card|alert-settings-card|步骤 1/, "no cards around the steps");
  assert.match(html, /<details class="ui-disclosure"><summary[^>]*>.*?测试规则/s, "the rule test starts closed");
  assert.match(html, /当前价 69,318\.23/, "the current chart's price sits under the product");
  assert.match(html, /class="alert-panel-footer".*创建警报/s);
});
