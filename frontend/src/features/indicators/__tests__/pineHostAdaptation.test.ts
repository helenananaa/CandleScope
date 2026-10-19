import type { SeriesAttachedParameter, Logical } from "lightweight-charts";
import type { ChartTime } from "../../../chart-adapter/chartAdapterTypes.js";
import { structuralMock } from "../../../test/testHelpers.js";
import { PineObjectPrimitive } from "../../../chart-adapter/pineObjectPrimitive.js";
import { klineDependencyKey, registerCacheResource, resetCacheRegistry } from "../../cache-gc/cacheRegistry.js";
import { cacheIndicatorSnapshot, getCachedIndicatorResult, resetIndicatorResultCache } from "../indicatorResultCacheStore.js";
import assert from "node:assert/strict";
import { parsePineContexts, pineContextParams } from "../PineContextInputs.js";
import { parsePineCurrencyRates, pineCurrencyParams } from "../PineCurrencyInputs.js";
import test from "node:test";

test("effective currency inputs preserve availability times and reject ambiguous or unordered data", () => {
  const rates = { schemaVersion: 1, pairs: [{ from: "USD", to: "EUR", rates: [{ effectiveTime: -1000, rate: 0.8 }, { effectiveTime: 1000, rate: 0.9 }] }] };
  assert.deepEqual(parsePineCurrencyRates(JSON.stringify(rates)), rates);
  assert.deepEqual(pineCurrencyParams({}, JSON.stringify(rates)), { __pineCurrencyRates: rates });
  assert.deepEqual(pineCurrencyParams({ __pineCurrencyRates: rates }, ""), {});
  for (const value of [{}, { ...rates, pairs: [...rates.pairs, ...rates.pairs] }, { ...rates, pairs: [{ ...rates.pairs[0], rates: [...rates.pairs[0]!.rates].reverse() }] }])
    assert.throws(() => parsePineCurrencyRates(JSON.stringify(value)));
});

test("Pine context settings preserve exact venue, timeframe and market and reject ambiguous keys", () => {
  const contexts = [{ symbol: "OKX:BTC-USDT", timeframe: "60", marketType: "spot" }];
  assert.deepEqual(parsePineContexts(JSON.stringify(contexts)), contexts);
  assert.deepEqual(pineContextParams({ length: 5 }, JSON.stringify(contexts)), { length: 5, __pineContexts: contexts });
  assert.deepEqual(pineContextParams({ __pineContexts: contexts, length: 5 }, "[]"), { length: 5 });
  for (const value of [{}, [{ symbol: "x", timeframe: "0" }], [...contexts, { ...contexts[0], marketType: "usdm" }], Array(17).fill(contexts[0])])
    assert.throws(() => parsePineContexts(JSON.stringify(value)));
});
import { normalizeIndicatorPayload } from "../indicatorPayloadRuntime.js";
import { createIndicatorOutputState, indicatorOutputReducer, filterIndicatorOutputStateByVisibility } from "../indicatorOutputReducer.js";
import { pineIndexTime, pineTimeLogical } from "../../../chart-adapter/pineObjectPrimitive.js";
import { pineLibraryParams, parsePineLibraries } from "../PineLibraryInputs.js";
import { buildIndicatorPaneData } from "../indicatorPaneProjection.js";

const scene = { id: "objects", pane: "separate", asOf: 300, times: [60, 120, 300], objects: [{ kind: "lines", row: { id: 1, x1: 1, x2: 1, y1: 8, y2: 12 } }] };

test("native object payload survives normalization, pane creation, hiding and deletion", () => {
  const normalized = normalizeIndicatorPayload({ drawings: [scene] }, "a");
  let state = indicatorOutputReducer(createIndicatorOutputState(), { type: "snapshot", indicatorId: "a", normalized });
  assert.equal(state.drawings?.[0]?.objects[0]?.row.x2, 1);
  assert.equal(buildIndicatorPaneData([{ id: "a", visible: true }], { drawings: state.drawings }).subPanes[0]?.id, "separate-a");
  assert.equal(filterIndicatorOutputStateByVisibility(state, [{ id: "a", visible: false }]).drawings?.length, 0);
  const older = normalizeIndicatorPayload({ drawings: [{ ...scene, asOf: 120, objects: [] }] }, "a");
  state = indicatorOutputReducer(state, { type: "replace-range", indicatorId: "a", normalized: older, range: { start: 60, end: 120 } });
  assert.equal(state.drawings?.[0]?.asOf, 300);
  state = indicatorOutputReducer(state, { type: "patch", indicatorId: "a", normalized: normalizeIndicatorPayload({ drawings: [{ ...scene, objects: [] }] }, "a") });
  assert.equal(state.drawings?.[0]?.objects.length, 0);
  state = indicatorOutputReducer(state, { type: "remove-indicator", indicatorId: "a" });
  assert.equal(state.drawings?.length, 0);
});

test("drawing coordinates preserve the original index timeline and gaps", () => {
  assert.equal(pineIndexTime(1.5, [60, 120, 300]), 210);
  assert.equal(pineIndexTime(3, [60, 120, 300]), 480);
  assert.equal(pineTimeLogical(210, [{ time: 120 }, { time: 300 }, { time: 480 }]), .5);
  assert.equal(pineTimeLogical(60, [{ time: 120 }, { time: 300 }]), -1 / 3);
});

test("versioned libraries remain in persisted params and preview identities", () => {
  const libraries = { "local/Math/1": '//@version=6\nlibrary("Math")\nexport twice(float x) => x * 2' };
  assert.deepEqual(pineLibraryParams({ length: 5 }, JSON.stringify(libraries)), { length: 5, __pineLibraries: libraries });
  assert.deepEqual(pineLibraryParams({ __pineLibraries: libraries, length: 5 }, "{}"), { length: 5 });
  assert.throws(() => parsePineLibraries('{"unversioned":"source"}'));
  assert.throws(() => parsePineLibraries('[]'));
});


test("object-only indicator snapshots retain cache coverage and immutable geometry", () => {
  resetIndicatorResultCache();
  const indicator = { id: "drawing-cache", script: "line.new(0,1,2,3)", language: "pine" };
  const context = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
  resetCacheRegistry();
  registerCacheResource("chart-data-cache", "binance-spot-BTCUSDT-1m", { type: "kline", dependencyKey: klineDependencyKey(context), bars: 3 });
  const normalized = normalizeIndicatorPayload({ drawings: [scene] }, indicator.id);
  const entry = cacheIndicatorSnapshot(indicator, context, normalized);
  assert.equal(entry?.coverage?.firstTime, 60);
  assert.equal(entry?.coverage?.lastTime, 300);
  assert.equal(getCachedIndicatorResult(indicator, context)?.normalized.drawings?.[0]?.objects[0]?.row.y2, 12);
});


test("future bar-index geometry advances one ordinal even after a timestamp gap", () => {
  const bars = [{ time: 60 }, { time: 120 }, { time: 300 }];
  const drawings = normalizeIndicatorPayload({ drawings: [{ ...scene, objects: [{ kind: "lines", row: { x1: 2, x2: 3, y1: 20, y2: 30 } }, { kind: "lines", row: { x1: 0, x2: 1, y1: -500, y2: -500 } }] }] }, "future").drawings || [];
  const primitive = new PineObjectPrimitive();
  primitive.attached(structuralMock<SeriesAttachedParameter<ChartTime>>({ chart: { timeScale: () => ({ options: () => ({ barSpacing: 10 }), logicalToCoordinate: (index: number) => index * 10 }) }, series: {}, requestUpdate() {} }));
  primitive.update(drawings, bars, (time) => time > 300 ? 20 + (time - 300) / 60 * 10 : pineTimeLogical(time, bars)! * 10);
  assert.deepEqual(primitive.autoscaleInfo(3 as Logical, 4 as Logical), { priceRange: { minValue: 30, maxValue: 30 } });
  primitive.detached();
});
