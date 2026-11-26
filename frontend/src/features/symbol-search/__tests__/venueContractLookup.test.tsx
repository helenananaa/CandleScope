import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { t } from "../../../i18n/index.js";
import { ContractPriceBadge, ContractPriceNotice } from "../ContractPriceBadge.js";
import { VenueContractLookup, type MarketSymbolRef, type VenueContractSearch } from "../venueContractLookup.js";
import type { SymbolSearchItem } from "../symbolSearchTypes.js";
import { nativeReportMarket } from "../../backtest/native/nativeReportMarket.js";

const gold: SymbolSearchItem = {
  symbol: "XAUUSDT", baseAsset: "XAU", quoteAsset: "USDT", exchange: "binance", marketType: "futures",
  assetClass: "crypto", underlyingClass: "commodity", _key: "binance:futures:XAUUSDT",
};
const bitcoin: SymbolSearchItem = { ...gold, symbol: "BTCUSDT", baseAsset: "BTC", _key: "binance:futures:BTCUSDT" };
delete bitcoin.underlyingClass;

function searcher(answers: Record<string, VenueContractSearch | Error>) {
  const calls: MarketSymbolRef[] = [];
  const search = async (ref: MarketSymbolRef): Promise<VenueContractSearch> => {
    calls.push(ref);
    const answer = answers[ref.symbol];
    if (answer instanceof Error) throw answer;
    return answer ?? { rows: [], settled: true };
  };
  return { calls, search };
}

test("a venue contract on a traditional market is found once and remembered", async () => {
  const { calls, search } = searcher({ XAUUSDT: { rows: [bitcoin, gold], settled: true } });
  const lookup = new VenueContractLookup(search);
  const market = { exchange: "Binance", marketType: "FUTURES", symbol: "xauusdt" };

  assert.equal(lookup.known(market), undefined);
  const [first, second] = await Promise.all([lookup.resolve(market), lookup.resolve(market)]);
  assert.deepEqual(first, { assetKey: "commodity", regionKey: null });
  assert.equal(second, first);
  assert.equal(calls.length, 1, "concurrent charts share one request");
  assert.deepEqual(calls[0], { exchange: "binance", marketType: "futures", symbol: "XAUUSDT" });
  assert.deepEqual(lookup.known(market), first);
  await lookup.resolve(market);
  assert.equal(calls.length, 1, "a remembered answer needs no request");
});

test("crypto contracts and spot markets carry no contract price label", async () => {
  const { calls, search } = searcher({ BTCUSDT: { rows: [bitcoin], settled: true } });
  const lookup = new VenueContractLookup(search);

  assert.equal(await lookup.resolve({ exchange: "binance", marketType: "futures", symbol: "BTCUSDT" }), null);
  assert.equal(lookup.known({ exchange: "binance", marketType: "futures", symbol: "BTCUSDT" }), null);
  assert.equal(lookup.known({ exchange: "binance", marketType: "spot", symbol: "XAUUSDT" }), null);
  assert.equal(await lookup.resolve({ exchange: "binance", marketType: "spot", symbol: "XAUUSDT" }), null);
  assert.equal(calls.length, 1, "spot rows are never looked up");
});

test("a symbol is only taken as plain once the catalog has answered", async () => {
  const { calls, search } = searcher({
    XAUUSDT: { rows: [], settled: false },
    CLUSDT: new Error("offline"),
  });
  const lookup = new VenueContractLookup(search);
  const gold = { exchange: "binance", marketType: "futures", symbol: "XAUUSDT" };
  const oil = { exchange: "binance", marketType: "futures", symbol: "CLUSDT" };

  assert.equal(await lookup.resolve(gold), null);
  assert.equal(lookup.known(gold), undefined, "a catalog still loading is asked again later");
  await assert.rejects(lookup.resolve(oil), /offline/);
  assert.equal(lookup.known(oil), undefined, "a failed request is asked again later");
  await lookup.resolve(gold);
  assert.equal(calls.filter((ref) => ref.symbol === "XAUUSDT").length, 2);
});

test("charts and reports show the contract price label for a known venue contract", async () => {
  const lookup = new VenueContractLookup(searcher({ XAUUSDT: { rows: [gold], settled: true } }).search);
  const market = { exchange: "binance", marketType: "futures", symbol: "XAUUSDT" };
  assert.equal(renderToStaticMarkup(<ContractPriceBadge market={market} lookup={lookup} />), "");
  await lookup.resolve(market);

  const badge = renderToStaticMarkup(<ContractPriceBadge market={market} lookup={lookup} />);
  assert.ok(badge.includes(t("search.contractPrice")));
  const notice = renderToStaticMarkup(<ContractPriceNotice market={market} lookup={lookup} />);
  assert.ok(notice.includes(t("search.contractPrice")) && notice.includes(t("search.contractPriceHint")));
  assert.equal(renderToStaticMarkup(<ContractPriceNotice market={null} lookup={lookup} />), "");
});

test("a Pine report finds its market from the run's exchange, market and context symbol", () => {
  const config = {
    source: "", language: "pine" as const, parameters: {}, exchange: "binance", market_type: "futures",
    context: { symbol: "BINANCE:XAUUSDT", timeframe: "60" },
  };
  assert.deepEqual(nativeReportMarket({ config } as Parameters<typeof nativeReportMarket>[0]),
    { exchange: "binance", marketType: "futures", symbol: "XAUUSDT" });
  const { exchange: _exchange, ...withoutExchange } = config;
  assert.equal(nativeReportMarket({ config: withoutExchange } as Parameters<typeof nativeReportMarket>[0]), null);
  assert.equal(nativeReportMarket({}), null);
});
