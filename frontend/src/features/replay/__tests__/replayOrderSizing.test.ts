import assert from "node:assert/strict";
import test from "node:test";

import {
  rebaseReplayMaxQuantity,
  replayOrderContextSide,
  replayOrderPreviewSide,
  replayOrderSizingAvailability,
  replayReduceOnlyUnavailableMessage,
  replayBoundClosingCapacity,
  replayOrderSideCapacity,
  replayQuantityForShare,
  replayQuantityForStep,
} from "../replayOrderSizing.js";

test("percentage submission uses the target side capacity with exact quantity steps", () => {
  assert.equal(replayQuantityForShare("76.27649932", 1, "0.00000001"), "76.27649932");
  assert.equal(replayQuantityForShare("76.28441487", 1, "0.00000001"), "76.28441487");
  assert.equal(replayQuantityForShare("76.27649932", 0.25, "0.00000001"), "19.06912483");
  assert.equal(replayQuantityForShare("1.005", 0.5, "0.005"), "0.5");
  assert.equal(replayQuantityForShare("100", 1, "1"), "100");
  assert.equal(replayQuantityForShare("0.00000009", 0.5, "1e-8"), "0.00000004");
  assert.equal(replayQuantityForShare("0", 1, "0.01"), "0");
  assert.equal(replayQuantityForShare("", 1, "0.01"), null);
  assert.equal(replayQuantityForShare("1", 2, "0.01"), null);
});

test("an empty short advisory cannot lock the held long closing action", () => {
  const shortCap = replayBoundClosingCapacity(null, true, 0);
  assert.equal(shortCap, "0");
  assert.equal(replayOrderSizingAvailability(
    replayOrderSideCapacity(shortCap, "BUY", "SELL", true, 1), "1",
  ).quantityExceedsCapacity, false);
  assert.equal(replayOrderSizingAvailability(
    replayOrderSideCapacity(shortCap, "BUY", "BUY", true, 0), "1",
  ).quantityExceedsCapacity, true);
});

test("unequal hedge legs and partial closes use each closing side's remaining quantity", () => {
  for (const [side, other] of [["BUY", "SELL"], ["SELL", "BUY"]] as const) {
    assert.equal(replayOrderSideCapacity("0.4", side, side, true, 0.4), "0.4");
    assert.equal(replayOrderSideCapacity("0.4", side, other, true, -2), "2");
    assert.equal(replayOrderSideCapacity("2", side, side, true, 0.4), "0.4");
    assert.equal(replayOrderSideCapacity("2", side, other, true, 0), "0");
    // An opening capacity from the other side remains unknown until revalidated.
    assert.equal(replayOrderSideCapacity("0", side, other, false, 0), null);
  }
});

test("close capacity follows full and partial closes instead of an old advisory", () => {
  for (const remaining of [0, 0.4, -0.4]) {
    const capacity = replayBoundClosingCapacity("1", true, remaining);
    assert.equal(capacity, String(Math.abs(remaining)));
    assert.equal(replayOrderSizingAvailability(capacity, "1").quantityExceedsCapacity, true);
    assert.equal(replayOrderSizingAvailability(capacity, "1").sliderDisabled, remaining === 0);
  }
  assert.equal(replayBoundClosingCapacity(null, true, 0), "0");
  assert.equal(replayBoundClosingCapacity(null, true, 1), null);
  assert.equal(replayBoundClosingCapacity("0.2", true, 1), "0.2");
  assert.equal(replayBoundClosingCapacity("1", false, 0), "1");
});

const BASE_INPUT = {
  previousMaxQuantity: 0.5,
  previousReferencePrice: 100,
  nextReferencePrice: 100,
  previousAvailableEquity: 10_000,
  nextAvailableEquity: 10_000,
  previousLeverage: 3,
  nextLeverage: 3,
  reduceOnly: false,
} as const;

test("rebases a stale 100% quantity downward before previewing a higher price", () => {
  const rebased = rebaseReplayMaxQuantity({
    ...BASE_INPUT,
    nextReferencePrice: 110,
  });

  assert.ok(rebased !== null);
  assert.ok(Math.abs(rebased - (0.5 * 100 / 110)) < 1e-12);
});

test("never grows a cached cap before the server confirms the new maximum", () => {
  assert.equal(rebaseReplayMaxQuantity({
    ...BASE_INPUT,
    nextReferencePrice: 90,
  }), 0.5);
});

test("rebases against lower equity and leverage without changing reduce-only capacity", () => {
  assert.equal(rebaseReplayMaxQuantity({
    ...BASE_INPUT,
    nextAvailableEquity: 8_000,
    nextLeverage: 2,
  }), 0.5 * 0.8 * (2 / 3));
  assert.equal(rebaseReplayMaxQuantity({
    ...BASE_INPUT,
    nextReferencePrice: 110,
    reduceOnly: true,
  }), 0.5);
});

test("known finite next equity at or below zero invalidates stale opening capacity", () => {
  assert.equal(rebaseReplayMaxQuantity({
    ...BASE_INPUT,
    nextAvailableEquity: 0,
  }), null);
  assert.equal(rebaseReplayMaxQuantity({
    ...BASE_INPUT,
    nextAvailableEquity: -10,
  }), null);
});

test("unknown previous equity still invalidates when next equity is known non-positive", () => {
  assert.equal(rebaseReplayMaxQuantity({
    ...BASE_INPUT,
    previousAvailableEquity: null,
    nextAvailableEquity: 0,
  }), null);
  assert.equal(rebaseReplayMaxQuantity({
    ...BASE_INPUT,
    previousAvailableEquity: Number.NaN,
    nextAvailableEquity: -10,
  }), null);
});

test("reduce-only keeps closing capacity when next equity is zero or negative", () => {
  assert.equal(rebaseReplayMaxQuantity({
    ...BASE_INPUT,
    nextAvailableEquity: 0,
    reduceOnly: true,
  }), 0.5);
  assert.equal(rebaseReplayMaxQuantity({
    ...BASE_INPUT,
    nextAvailableEquity: -10,
    reduceOnly: true,
  }), 0.5);
});

test("previews the only non-reversing side once a position is open", () => {
  assert.equal(replayOrderPreviewSide(0, "BUY"), "BUY");
  assert.equal(replayOrderPreviewSide(0, "SELL"), "SELL");
  assert.equal(replayOrderPreviewSide(1, "SELL"), "BUY");
  assert.equal(replayOrderPreviewSide(-1, "BUY"), "SELL");
});

test("capacity context follows the closing side for reduce-only orders", () => {
  assert.equal(replayOrderContextSide(1, "BUY", true), "SELL");
  assert.equal(replayOrderContextSide(-1, "SELL", true), "BUY");
  assert.equal(replayOrderContextSide(0, "SELL", true), "SELL");
  assert.equal(replayOrderContextSide(1, "SELL", false), "BUY");
});

test("reduce-only advisories stop locally when the selected leg is empty", () => {
  assert.equal(replayReduceOnlyUnavailableMessage({
    reduceOnly: false,
    positionQuantity: 0,
    positionMode: "ONE_WAY",
    targetPositionSide: "LONG",
  }), null);
  assert.equal(replayReduceOnlyUnavailableMessage({
    reduceOnly: true,
    positionQuantity: 1,
    positionMode: "ONE_WAY",
    targetPositionSide: "LONG",
  }), null);
  assert.equal(replayReduceOnlyUnavailableMessage({
    reduceOnly: true,
    positionQuantity: 0,
    positionMode: "ONE_WAY",
    targetPositionSide: "SHORT",
  }), "无持仓可平");
  assert.equal(replayReduceOnlyUnavailableMessage({
    reduceOnly: true,
    positionQuantity: 0,
    positionMode: "HEDGE",
    targetPositionSide: "LONG",
  }), "无多仓可平");
  assert.equal(replayReduceOnlyUnavailableMessage({
    reduceOnly: true,
    positionQuantity: 0,
    positionMode: "HEDGE",
    targetPositionSide: "SHORT",
  }), "无空仓可平");
});

test("an oversized rejected draft cannot destroy independent slider capacity", () => {
  const authoritativeCapacity = "0.50898188";
  const oversized = replayOrderSizingAvailability(authoritativeCapacity, "999999999");
  assert.equal(oversized.sliderDisabled, false);
  assert.equal(oversized.quantityExceedsCapacity, true);

  const corrected = replayOrderSizingAvailability(authoritativeCapacity, "0.001");
  assert.equal(corrected.sliderDisabled, false);
  assert.equal(corrected.quantityExceedsCapacity, false);
});

test("a known zero capacity flags a positive draft without enabling the slider", () => {
  const positiveDraft = replayOrderSizingAvailability("0", "0.001");
  assert.equal(positiveDraft.sliderDisabled, true);
  assert.equal(positiveDraft.quantityExceedsCapacity, true);

  const zeroDraft = replayOrderSizingAvailability("0", "0");
  assert.equal(zeroDraft.sliderDisabled, true);
  assert.equal(zeroDraft.quantityExceedsCapacity, false);
});

test("unknown or invalid maximum does not flag excess capacity", () => {
  for (const maxQuantity of [null, "", "   ", "not-a-number", "-1"]) {
    const availability = replayOrderSizingAvailability(maxQuantity, "0.001");
    assert.equal(availability.sliderDisabled, true);
    assert.equal(availability.quantityExceedsCapacity, false);
  }
});

test("aligned maximum quantities survive draft and preview quantization", () => {
  for (const quantity of ["39.27189899", "19.63594949", "0.00000003", "76.27649932"]) {
    const displayed = replayQuantityForStep(Number(quantity), "0.00000001");
    assert.equal(displayed, quantity);
    assert.equal(replayQuantityForStep(Number(displayed), "0.00000001"), quantity);
    assert.equal(displayed, replayQuantityForShare(quantity, 1, "0.00000001"));
  }
  assert.equal(replayQuantityForStep(1.009, "0.005"), "1.005");
  assert.equal(replayQuantityForStep(0.000000029, "1e-8"), "0.00000002");
});
