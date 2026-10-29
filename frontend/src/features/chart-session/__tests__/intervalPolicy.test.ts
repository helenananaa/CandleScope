import assert from "node:assert/strict";
import test from "node:test";

import {
  canResolveIntervalForSeriesIdentity,
  getEffectiveCustomIntervalRecords,
  getFallbackIntervalAfterCustomClear,
  getFallbackIntervalAfterCustomRemove,
  isExchangeIntervalCapabilityAvailable,
  resolveRequestedInterval,
} from "../intervalPolicy.js";
import type { CustomIntervalRecord } from "../chartSessionTypes.js";

const nativeIntervals = [
  { value: "1m", seconds: 60 },
  { value: "1h", seconds: 3600 },
  { value: "1d", seconds: 86400 },
];
const twelveDataNasdaqIdentity = {
  providerId: "twelvedata",
  venue: "xnas",
  assetClass: "equity",
  seriesVariant: "native",
  priceAdjustment: "raw",
  sessionVariant: "regular",
  volumeSemantics: "shares",
};

test("exchange capability readiness distinguishes loading, explicit fallback, and ready-empty catalogs", () => {
  assert.equal(isExchangeIntervalCapabilityAvailable("loading", {}, "binance", nativeIntervals), false);
  assert.equal(isExchangeIntervalCapabilityAvailable("fallback", {}, "binance", nativeIntervals), true);
  assert.equal(isExchangeIntervalCapabilityAvailable("fallback", {}, "unknown", []), false);
  assert.equal(isExchangeIntervalCapabilityAvailable("ready", {}, "binance", nativeIntervals), false);
  assert.equal(isExchangeIntervalCapabilityAvailable("ready", {
    binance: {} as never,
  }, "binance", nativeIntervals), true);
});

function customInterval(value: string, lastUsedAt: number): CustomIntervalRecord {
  return {
    value,
    createdAt: 0,
    lastUsedAt,
    usageCount: 0,
    pinned: false,
    order: 0,
  };
}

test("restoring a requested interval does not depend on favorites or capability", () => {
  for (const interval of ["89m", "7s", "1d"]) {
    assert.equal(resolveRequestedInterval({ interval, nativeIntervals }), interval);
    assert.equal(resolveRequestedInterval({ interval, nativeIntervals: [] }), interval);
  }
  assert.equal(resolveRequestedInterval({ interval: "bad", nativeIntervals }), "1h");
  assert.equal(resolveRequestedInterval({ interval: "120s", nativeIntervals }), "2m");
});

test("non-default series identities allow native intervals but reject derived custom intervals", () => {
  const nativeValues = nativeIntervals.map((item) => item.value);

  assert.equal(canResolveIntervalForSeriesIdentity(
    "twelvedata",
    "1m",
    nativeValues,
    twelveDataNasdaqIdentity,
  ), true);
  assert.equal(canResolveIntervalForSeriesIdentity(
    "twelvedata",
    "7m",
    nativeValues,
    twelveDataNasdaqIdentity,
  ), false);
  assert.equal(canResolveIntervalForSeriesIdentity(
    "binance",
    "7m",
    nativeValues,
    undefined,
  ), true);
  assert.equal(resolveRequestedInterval({
    interval: "7m",
    nativeIntervals,
  }), "7m");
  assert.equal(resolveRequestedInterval({
    interval: "1m",
    nativeIntervals,
  }), "1m");
});

test("custom interval removal prefers recent custom then nearest native interval", () => {
  const isNative = (_exchange: string, interval: string) => nativeIntervals.some((item) => item.value === interval);
  assert.equal(getFallbackIntervalAfterCustomRemove({
    removedInterval: "30m",
    customIntervalRecords: [
      customInterval("7s", 3),
      customInterval("20m", 1),
      customInterval("45m", 2),
    ],
    nativeIntervals,
    exchange: "binance",
    isNativeIntervalSupported: isNative,
  }), "45m");
  assert.equal(getFallbackIntervalAfterCustomRemove({
    removedInterval: "45m",
    customIntervalRecords: [],
    nativeIntervals,
    exchange: "binance",
    isNativeIntervalSupported: isNative,
  }), "1h");
  assert.equal(getFallbackIntervalAfterCustomRemove({
    removedInterval: "7m",
    customIntervalRecords: [customInterval("45m", 2)],
    nativeIntervals,
    exchange: "twelvedata",
    marketType: "stock",
    isNativeIntervalSupported: isNative,
    seriesIdentity: twelveDataNasdaqIdentity,
  }), "1m");
  assert.equal(getFallbackIntervalAfterCustomClear({
    interval: "50m",
    nativeIntervals,
  }), "1h");
});

test("saved custom provenance is masked when the current exchange supports it natively", () => {
  const records = [customInterval("8h", 2), customInterval("45m", 1)];
  const nativeWithEightHours = [
    ...nativeIntervals,
    { value: "8h", seconds: 28_800 },
  ];

  assert.deepEqual(
    getEffectiveCustomIntervalRecords(records, nativeWithEightHours).map((record) => record.value),
    ["45m"],
  );
  assert.equal(getFallbackIntervalAfterCustomRemove({
    removedInterval: "8h",
    customIntervalRecords: records,
    nativeIntervals: nativeWithEightHours,
    exchange: "binance",
    isNativeIntervalSupported: (_exchange, interval) => interval === "8h",
  }), "8h");
  assert.equal(getFallbackIntervalAfterCustomClear({
    interval: "8h",
    nativeIntervals: nativeWithEightHours,
  }), "8h");
});

test("semantic aliases migrate onto the native canonical interval", () => {
  assert.deepEqual(getEffectiveCustomIntervalRecords([
    customInterval("60m", 1),
    customInterval("24h", 2),
    customInterval("7d", 3),
  ], nativeIntervals).map((record) => record.value), ["7d"]);
  assert.equal(resolveRequestedInterval({
    interval: "60m",
    nativeIntervals,
  }), "1h");
  assert.equal(getFallbackIntervalAfterCustomClear({
    interval: "24h",
    nativeIntervals,
  }), "1d");
});
