import assert from "node:assert/strict";
import test from "node:test";
import { alertExpressionDraftSchema, alertDraftPatchSchema } from "./alertCommandSchema.js";
import { canonicalWatchlistSymbol } from "./watchlistCommands.js";

const condition = { id: "condition", type: "condition", not: false, left: "close", comparator: ">", rightType: "number", rightValue: "100", rangeMin: "", rangeMax: "", percentValue: "" };
test("alert drafts reject unknown fields and enforce expression node and nesting budgets", () => {
  assert.deepEqual(alertDraftPatchSchema.parse({ expression: condition }), { expression: condition });
  assert.throws(() => alertDraftPatchSchema.parse({ arbitraryExecutor: "x" }));
  assert.throws(() => alertExpressionDraftSchema.parse({ ...condition, execute: "x" }));
  const group = (children: unknown[]) => ({ id: "group", type: "group", not: false, op: "AND", children });
  assert.throws(() => alertExpressionDraftSchema.parse(group(Array.from({ length: 256 }, () => condition))), /EXPRESSION_LIMIT/);
  let nested: unknown = condition; for (let n = 0; n < 17; n++) nested = group([nested]);
  assert.throws(() => alertExpressionDraftSchema.parse(nested), /EXPRESSION_LIMIT/);
});
test("watchlist import accepts only canonical symbol identities", () => {
  for (const key of ["spot:BTCUSDT", "okx:spot:BTC-USDT", "futures:ETHUSDT"]) assert.equal(canonicalWatchlistSymbol.parse(key), key);
  for (const key of ["BTCUSDT", "spot:btcusdt", "binance:spot:BTCUSDT", "okx:spot:BTC-USDT:extra", "spot:", "spot:BTC USDT"]) assert.throws(() => canonicalWatchlistSymbol.parse(key));
});
