import assert from "node:assert/strict";
import test from "node:test";
import { pineContractMetadata, quantityDecimalPlaces, validatePineContractMetadata } from "../pineContractMetadata.js";
import { parsePineContexts } from "../pineContextModel.js";

test("exact quantity metadata preserves micro contracts and minimum independent of step", () => {
  for (const quantityStep of [".25", "+0.2500", "25e-2", "2e-12", "1e-18"]) {
    const metadata = pineContractMetadata({ priceTickSize: ".1", pointValue: "50", quantityStep, minContract: "2" });
    assert.deepEqual(metadata, { priceTickSize: ".1", pointValue: 50, quantityStep, minContract: "2" });
    const contexts = [{ symbol: "EXCHANGE:B", timeframe: "1", metadata }];
    assert.deepEqual(parsePineContexts(JSON.stringify(contexts)), contexts);
  }
  assert.equal(quantityDecimalPlaces("25e-2"), 2);
  assert.equal(quantityDecimalPlaces("1e-18"), 18);
  assert.equal(pineContractMetadata({}), undefined);
});

test("invalid or lossy contract inputs are rejected before freezing data", () => {
  for (const value of [true, .25, "0", "-1", "NaN", "1/4", "1e-19", "1e100000000000000000", "0.100000000000000001", "18446744073709551616"])
    for (const key of ["quantityStep", "minContract"])
      assert.throws(() => validatePineContractMetadata({ priceTickSize: ".1", [key]: value }));
  for (const pointValue of [0, -1, NaN, Infinity, true, "50"])
    assert.throws(() => validatePineContractMetadata({ priceTickSize: ".1", pointValue }));
  assert.throws(() => pineContractMetadata({ pointValue: "50" }), /actual price tick/);
  assert.throws(() => pineContractMetadata({ priceTickSize: ".1", quantityStep: ".25", quantityPrecision: "1" }), /precision/);
  assert.doesNotThrow(() => pineContractMetadata({ priceTickSize: ".1", quantityStep: ".25", quantityPrecision: "2" }));
});
