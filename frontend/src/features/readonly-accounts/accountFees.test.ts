import assert from "node:assert/strict";
import test from "node:test";
import { feeRateEstimate, formatFeeRate } from "./accountFees.js";

const rates = { tier: "Lv2", usdtMargined: { maker: "-0.00005", taker: "0.00045" }, coinMargined: null, exchangeTimeMs: 1_709_251_200_000 };

test("fee rates are an estimate per settlement with tier and both times", () => {
  assert.deepEqual(feeRateEstimate({ fee_rates: { receivedMs: 5, data: { raw: {}, rates } }, fee_rates_state: { receivedMs: 5, data: { error: null } } }), {
    tier: "Lv2", settlements: [{ settlement: "usdtMargined", rates: { maker: "-0.00005", taker: "0.00045" } }],
    exchangeTimeMs: 1_709_251_200_000, receivedMs: 5, error: null,
  });
});

test("a failed read keeps the earlier rates and says why; a first failure has no rates", () => {
  const kept = feeRateEstimate({ fee_rates: { receivedMs: 5, data: { rates } }, fee_rates_state: { receivedMs: 9, data: { error: "ACCOUNT_NETWORK_UNAVAILABLE" } } })!;
  assert.equal(kept.error, "ACCOUNT_NETWORK_UNAVAILABLE");
  assert.equal(kept.settlements.length, 1);
  const none = feeRateEstimate({ fee_rates_state: { receivedMs: 9, data: { error: "FEE_RATES_UNAVAILABLE" } } })!;
  assert.deepEqual(none.settlements, []);
  assert.equal(none.receivedMs, null);
  assert.equal(feeRateEstimate({}), null);
});

test("malformed rates are unknown, never zero", () => {
  const value = feeRateEstimate({ fee_rates: { receivedMs: 5, data: { rates: { ...rates, usdtMargined: { maker: "1e-4", taker: 3 } } } } })!;
  assert.deepEqual(value.settlements[0]!.rates, { maker: null, taker: null });
});

test("rates read as percentages and rebates are marked, not shown as negative fees", () => {
  assert.deepEqual(formatFeeRate("0.00045", "en"), { text: "0.045%", rebate: false });
  assert.deepEqual(formatFeeRate("-0.00005", "en"), { text: "0.005%", rebate: true });
  assert.deepEqual(formatFeeRate("0.0002", "en"), { text: "0.020%", rebate: false });
  assert.deepEqual(formatFeeRate("0", "en"), { text: "0.000%", rebate: false });
});
