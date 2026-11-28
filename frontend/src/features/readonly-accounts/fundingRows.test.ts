import assert from "node:assert/strict";
import test from "node:test";
import { fundingBalances, fundingHistory, fundingReadError, shownAmount } from "./fundingRows.js";

test("funding balances come from their own snapshot; malformed rows are dropped, not zeroed", () => {
  assert.equal(fundingBalances({}), null);
  const value = fundingBalances({ funding_balances: { receivedMs: 7, data: { balances: [
    { currency: "USDT", total: "10", available: "9", frozen: "1" },
    { currency: "BTC", total: "-1", available: "0", frozen: "0" },
    { currency: "ETH", total: "1e3", available: "0", frozen: "0" },
  ] } } })!;
  assert.deepEqual(value, { balances: [{ currency: "USDT", total: "10", available: "9", frozen: "1" }], receivedMs: 7 });
});

test("read failures are reported per kind", () => {
  const snapshots = { funding_balances_state: { receivedMs: 1, data: { error: "ACCOUNT_NETWORK_UNAVAILABLE" } },
    funding_history_state: { receivedMs: 1, data: { error: null, complete: true } } };
  assert.equal(fundingReadError(snapshots, "funding_balances"), "ACCOUNT_NETWORK_UNAVAILABLE");
  assert.equal(fundingReadError(snapshots, "funding_history"), null);
});

test("history merges deposits, withdrawals and transfers newest first with their signs", () => {
  assert.equal(fundingHistory({ receivedMs: null, data: null }), null);
  const history = fundingHistory({ receivedMs: 50, data: {
    deposits: [{ id: "d", currency: "BTC", amount: "0.5", chain: "BTC-Bitcoin", state: "completed", eventTimeMs: 10 }],
    withdrawals: [{ id: "w", currency: "USDT", amount: "100", chain: "USDT-TRC20", state: "mystery", fee: "1", feeCurrency: "USDT", eventTimeMs: 30 }],
    transfers: [{ id: "t", currency: "USDT", amount: "25", direction: "out", from: "trading", to: "funding", eventTimeMs: 20 },
      { id: "bad", currency: "USDT", amount: "25", direction: "sideways", from: "trading", to: "funding", eventTimeMs: 25 }],
    fromMs: 1, throughMs: 50, complete: false,
  } })!;
  assert.deepEqual(history.rows.map((row) => row.id), ["w", "t", "d"]);
  assert.equal(history.complete, false);
  assert.equal(history.rows[0]!.kind === "withdrawal" && history.rows[0]!.state, "unknown");
  // A transfer's sign depends on the side it is seen from, so it shows the bare amount and its route.
  assert.deepEqual(history.rows.map(shownAmount), ["−100", "25", "+0.5"]);
});
