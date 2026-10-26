import assert from "node:assert/strict";
import test from "node:test";
import { parseReviewListing, parseReviewTrade, reviewJournalApi } from "./reviewApi.js";
import { positionAt, replayEvents } from "../trading-accounts/quickReplayModel.js";

const trade = {
  id: "ro_"+"1".repeat(20), accountId: "acc_"+"2".repeat(20), exchange: "okx", marketType: "futures", symbol: "BTCUSDT",
  direction: "long", status: "closed", openedAtMs: 1000, closedAtMs: 9000, openQty: "0", maxQty: "0.02",
  entryQty: "0.02", exitQty: "0.02", avgEntryPrice: "10000", avgExitPrice: "20000", realizedPnl: "200", fees: "0.2", netPnl: "199.6",
  markPrice: null, unrealizedPnl: null,
  legs: [
    { fillId: "1", side: "buy", role: "open", qty: "0.02", price: "10000", fee: "0.1", tsMs: 1000, liquidity: "exchange", orderId: "21" },
    { fillId: "2", side: "sell", role: "close", qty: "0.02", price: "20000", fee: "0.1", tsMs: 9000, liquidity: "exchange", orderId: "22" },
  ],
  readonlySource: { venue: "okx", accountUid: "synthetic", product: "SWAP", instrument: "BTC-USDT-SWAP", positionId: "100",
    marginMode: "cross", currency: "USDT", version: "a".repeat(64), verifiedAtMs: 10000, current: true, funding: "-0.2",
    fills: [
      { fillId: "1", tradeId: "41", orderId: "21", contracts: "2", contractValue: "0.01", realizedPnl: "0", tsMs: 1000 },
      { fillId: "2", tradeId: "42", orderId: "22", contracts: "2", contractValue: "0.01", realizedPnl: "200", tsMs: 9000 },
    ], fundingEvents: [{ billId: "3", eventTimeMs: 5000, amount: "-0.2" }],
  },
};

test("verified review rejects unsupported currencies and invalid financial values", () => {
  assert.equal(parseReviewTrade(trade).id, trade.id);
  assert.throws(() => parseReviewTrade({ ...trade, netPnl: 199.6 }));
  assert.throws(() => parseReviewTrade({ ...trade, readonlySource: { ...trade.readonlySource, currency: "BTC" } }));
  assert.throws(() => parseReviewTrade({ ...trade, readonlySource: { ...trade.readonlySource, fundingEvents: [{ billId: "3", eventTimeMs: 5000, amount: NaN }] } }));
  assert.throws(() => parseReviewListing({ trades: [trade], stats: { count: 1 } }));
});

test("replay includes only observed fills and settled funding before the cursor, including rewind", () => {
  const verified = parseReviewTrade(trade);
  for (const [cursor, pnl, funding] of [[1, 0, 0], [2, -0.1, 0], [5, -0.1, 0], [6, -0.3, -0.2], [9, -0.3, -0.2], [10, 199.6, -0.2], [2, -0.1, 0]]) {
    const position = positionAt(verified, [], cursor!, 1);
    assert.equal(position.funding, funding);
    assert.ok(Math.abs(position.realized - position.fees + position.funding - pnl!) < 1e-10);
  }
  assert.equal(trade.readonlySource.fundingEvents.length, 1);
  assert.deepEqual(replayEvents(verified, []).map((event) => event.kind), ["fill", "funding", "fill"]);
});

test("review transport pins the financial version and protects reads, notes and snapshot images", async () => {
  const oldWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const oldFetch = globalThis.fetch;
  const calls: { url: string; init?: RequestInit }[] = [];
  const session = { apiBase: "http://127.0.0.1:8123/api/v2/plugins", sessionToken: "s".repeat(40), csrfToken: "c".repeat(40) };
  Object.defineProperty(globalThis, "window", { configurable: true, value: { candlescopeDesktop: { getPluginManagementSession: () => session } } });
  const entry = { id: "je_"+"3".repeat(20), accountId: trade.accountId, fields: {}, snapshots: [], tags: [], revisionCount: 1 };
  globalThis.fetch = async (input, init) => {
    calls.push({ url: String(input), ...(init ? { init } : {}) });
    return new Response(JSON.stringify(String(input).endsWith("/image") ? { image: "data:image/png;base64,AAAA" }
      : init?.method === "POST" ? entry : { ...trade, entries: [], linkSuggestions: [] }), { status: 200 });
  };
  try {
    const api = reviewJournalApi(parseReviewTrade(trade));
    await api.trade(trade.accountId, trade.id);
    await api.createEntry(trade.accountId, { tradeId: trade.id, clientEntryId: entry.id });
    await api.snapshotImageUrl("snp_"+"4".repeat(20));
    assert.match(calls[0]!.url, /\/readonly-accounts\/review\/accounts\/.*\?version=a{64}$/);
    for (const call of calls) {
      assert.equal(new Headers(call.init?.headers).get("X-CandleScope-Plugin-Session"), session.sessionToken);
      assert.equal(call.init?.credentials, "omit");
      assert.equal(call.init?.redirect, "error");
      assert.ok(!call.url.includes(session.sessionToken));
    }
    assert.equal(new Headers(calls[1]!.init?.headers).get("X-CandleScope-CSRF"), session.csrfToken);
    assert.equal(new Headers(calls[1]!.init?.headers).get("X-CandleScope-User-Action"), "account.review");
  } finally {
    globalThis.fetch = oldFetch;
    if (oldWindow) Object.defineProperty(globalThis, "window", oldWindow);
    else Reflect.deleteProperty(globalThis, "window");
  }
});
