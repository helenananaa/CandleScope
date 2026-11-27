import assert from "node:assert/strict";
import test from "node:test";
import { capabilityRoleContract, continuousMarketSupported } from "../capabilityRoles.js";

const binance = { roles: [
  { role: "contract_rules", market_types: ["futures"], contract: "BINANCE_USDM_LINEAR_BASE_QUANTITY" },
  { role: "trades.history.archive", market_types: ["FUTURES"], contract: "binance.public-data.um-agg-trades.daily/1" },
] };

test("role lookups match the market and return the declared contract", () => {
  assert.equal(capabilityRoleContract(binance, " Futures ", "trades.history.archive"), "binance.public-data.um-agg-trades.daily/1");
  assert.equal(capabilityRoleContract(binance, "spot", "contract_rules"), null);
  assert.equal(capabilityRoleContract(null, "futures", "contract_rules"), null);
  assert.equal(capabilityRoleContract({}, "futures", "contract_rules"), null);
});

test("continuous futures need the venue's base-quantity contract rules; spot needs none", () => {
  assert.equal(continuousMarketSupported(binance, "futures"), true);
  assert.equal(continuousMarketSupported({ roles: [] }, "futures"), false);
  assert.equal(continuousMarketSupported(null, "futures"), false);
  assert.equal(continuousMarketSupported({ roles: [{ ...binance.roles[0]!, contract: "acme/1" }] }, "futures"), false);
  assert.equal(continuousMarketSupported({ roles: [] }, "spot"), true);
  assert.equal(continuousMarketSupported(binance, "swap.linear"), false);
  // Unknown until the exchange catalog loads: the backend decides.
  assert.equal(continuousMarketSupported(undefined, "futures"), true);
});
