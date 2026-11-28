import assert from "node:assert/strict";
import test from "node:test";
import { fallbackMarketRules } from "./practiceMarketRules.js";

test("undeclared markets keep the earlier practice rules, the same fallback the backend uses", () => {
  assert.deepEqual(fallbackMarketRules("futures"), {
    accountModel: "crypto_linear", declared: false, leverage: true, shorting: true, hedge: true, opensPositions: true,
  });
  for (const marketType of ["spot", "stock", "swap.linear"]) {
    const rules = fallbackMarketRules(marketType);
    assert.equal(rules.accountModel, "cash");
    assert.equal(rules.shorting || rules.hedge || rules.leverage, false);
    assert.equal(rules.opensPositions, true);
  }
});
