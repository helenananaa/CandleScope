import assert from "node:assert/strict";
import test from "node:test";
import { sortWatchlists } from "../watchlistSort.js";
import type { WatchlistPriceSnapshot } from "../watchlistPriceStore.js";

const group = { id: "qa", name: "QA", color: "blue", symbols: ["BTCUSDT", "ETHUSDT", "SOLUSDT", "MISSING"] };
const prices: WatchlistPriceSnapshot = {
  BTCUSDT: { symbol: "BTCUSDT", price: 79000, daily_change: 200, daily_change_pct: 0.25 },
  ETHUSDT: { symbol: "ETHUSDT", price: 2500, daily_change: -10, daily_change_pct: -0.4 },
  SOLUSDT: { symbol: "SOLUSDT", price: 104, open: 102, change_pct: 2 },
};

test("price sorting is numeric, missing quotes last in both directions", () => {
  assert.deepEqual(sortWatchlists([group], "price", "asc", prices)[0]?.symbols, ["SOLUSDT", "ETHUSDT", "BTCUSDT", "MISSING"]);
  assert.deepEqual(sortWatchlists([group], "price", "desc", prices)[0]?.symbols, group.symbols);
});
test("change and percentage use the same daily values and fallback as displayed rows", () => {
  assert.deepEqual(sortWatchlists([group], "change", "asc", prices)[0]?.symbols, ["ETHUSDT", "SOLUSDT", "BTCUSDT", "MISSING"]);
  assert.deepEqual(sortWatchlists([group], "changePct", "desc", prices)[0]?.symbols, ["SOLUSDT", "BTCUSDT", "ETHUSDT", "MISSING"]);
});
test("disabled and non-finite quotes stay last without changing their relative order", () => {
  const invalid = { ...prices, SOLUSDT: { symbol: "SOLUSDT", price: NaN } };
  assert.deepEqual(sortWatchlists([group], "price", "asc", invalid, { BTCUSDT: "none" })[0]?.symbols, ["ETHUSDT", "BTCUSDT", "SOLUSDT", "MISSING"]);
});
test("stable ties, independent groups, and immutable input", () => {
  const second = { ...group, id: "two", symbols: ["ETHUSDT", "BTCUSDT"] };
  const before = structuredClone([group, second]);
  const result = sortWatchlists([group, second], "change", "asc", {});
  assert.deepEqual(result, before);
  assert.notEqual(result[0]?.symbols, group.symbols);
  assert.deepEqual([group, second], before);
});
test("symbol order uses display symbol rather than exchange prefix", () => {
  const items = { ...group, symbols: ["binance:spot:SOLUSDT", "okx:spot:BTC-USDT"] };
  assert.deepEqual(sortWatchlists([items], "symbol", "asc", {})[0]?.symbols, ["okx:spot:BTC-USDT", "binance:spot:SOLUSDT"]);
});
