import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import SymbolSearchModal from "../SymbolSearchModal.js";

function modal() {
  return renderToStaticMarkup(<SymbolSearchModal open onClose={() => undefined} onSelect={() => undefined}
    currentSymbol="BTCUSDT" currentMarketType="spot" currentExchange="binance" />);
}

test("symbol search filters are one row of labelled kit selects under a scope switch", () => {
  const html = modal();
  assert.match(html, /role="radiogroup" aria-label="范围"/);
  assert.equal((html.match(/role="radio"/g) ?? []).length, 3);
  const labels = [...html.matchAll(/<(?:label|span) class="ui-field-label"[^>]*>([^<]+)</g)].map((match) => match[1]);
  assert.deepEqual(labels, ["资产类别", "数据来源", "交易所", "类型", "计价"]);
  assert.equal((html.match(/<select[^>]*class="ui-input ui-input-sm ui-select"/g) ?? []).length, 4);
  assert.match(html, /<summary class="ui-input ui-input-sm ui-select sym-source-trigger" aria-label="数据来源: 全部">/);
  assert.doesNotMatch(html, /sym-modal-market-tab|sym-modal-exchange-select|sym-modal-chip/);
});

test("the list's columns use search's own labels and the close button is a kit icon button", () => {
  const html = modal();
  assert.match(html, /<div class="sym-modal-table-header" aria-hidden="true">.*名称.*数据来源/s);
  assert.match(html, /<button[^>]*class="ui-icon-btn ui-icon-btn-sm sym-modal-close-btn"[^>]*aria-label="关闭 \(Esc\)"/);
  assert.doesNotMatch(html, /<svg[^>]*><line/, "no hand-drawn close glyph");
});
