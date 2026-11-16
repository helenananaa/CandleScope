import { LOCALES as lazyTestLocales, loadLocaleCatalog } from "../../../i18n/registry.js";

test.before(async () => { await Promise.all(lazyTestLocales.map(loadLocaleCatalog)); });

import assert from "node:assert/strict";
import test from "node:test";
import { setLocale } from "../../../i18n/index.js";
import { cacheEntryLabel } from "../cacheEntryLabel.js";

test("series cache keys read as exchange, market, symbol and interval", () => {
  setLocale("zh-CN");
  assert.equal(cacheEntryLabel("2\u0000binance-spot-BTCUSDT-1m"), "币安 · 现货 · BTCUSDT · 1m");
  assert.equal(cacheEntryLabel("okx-swap-BTC-USDT-SWAP-15m"), "OKX · 永续 · BTC-USDT-SWAP · 15m");
  assert.equal(cacheEntryLabel("chart:1:binance-spot-BTCUSDT-1h"), "币安 · 现货 · BTCUSDT · 1h");
  setLocale("en");
  assert.equal(cacheEntryLabel("binance-spot-ETHUSDT-1h"), "Binance · Spot · ETHUSDT · 1h");
});

test("other cache keys stay as they are, with visible separators", () => {
  assert.equal(cacheEntryLabel("indicator\u0000ema-20"), "indicator · ema-20");
  assert.equal(cacheEntryLabel(""), "—");
  assert.equal(cacheEntryLabel(undefined), "—");
});
