import assert from "node:assert/strict";
import test from "node:test";

import { klineDependencyKey, registerCacheResource, resetCacheRegistry } from "../../cache-gc/cacheRegistry.js";
import { stripIndicatorRuntimeFields } from "../activeIndicatorStore.js";
import {
  parseIndicatorPayloadEnvelope,
  parseIndicatorRangeBatchResponse,
  parseIndicatorSeedState,
} from "../indicatorContracts.js";
import { hydrateIndicatorDefinitionsFromCache } from "../indicatorHydrationRuntime.js";
import { buildIndicatorPaneData } from "../indicatorPaneProjection.js";
import { normalizeParsedIndicatorPayload } from "../indicatorPayloadRuntime.js";
import {
  cacheIndicatorSnapshot,
  getCachedIndicatorResult,
  patchCachedIndicatorResult,
  replaceCachedIndicatorRange,
  resetIndicatorResultCache,
} from "../indicatorResultCacheStore.js";
import {
  partialSeedRangeAt,
  partialSeedRangeFor,
  replacePartialSeedRanges,
  updatePartialSeedRanges,
  withPartialSeed,
} from "../indicatorSeedState.js";
import type { IndicatorLine, IndicatorPartialSeedRange } from "../indicatorTypes.js";

const partial = { state: "partial", warmupBars: 5, seedBars: 2 } as const;
const converged = { state: "converged", warmupBars: 5, seedBars: 5 } as const;

function line(times: readonly number[]): IndicatorLine {
  return { outputName: "ema", data: times.map((time) => ({ time, value: time / 10 })) };
}

function span(start: number, end: number, seedBars = 2): IndicatorPartialSeedRange {
  return { start, end, warmupBars: 5, seedBars };
}

test("range payloads carry the backend seed state", () => {
  const payload = parseIndicatorPayloadEnvelope({
    type: "indicator.replace_range",
    range: { start: 100, end: 900 },
    seed: { state: "partial", warmupBars: 2964, seedBars: 100 },
  });
  assert.deepEqual(payload.seed, { state: "partial", warmupBars: 2964, seedBars: 100 });

  const batch = parseIndicatorRangeBatchResponse({ ok: true, results: [
    { clientId: "ema", payload: { range: { start: 1, end: 2 }, seed: converged } },
    { clientId: "rsi", payload: { range: { start: 1, end: 2 } } },
  ] });
  assert.deepEqual(batch.results.map((result) => result.payload.seed), [converged, undefined]);
});

test("seed parsing is tolerant: absent or malformed seeds leave the payload valid", () => {
  assert.equal("seed" in parseIndicatorPayloadEnvelope({ range: { start: 1, end: 2 } }), false);
  for (const seed of [
    null,
    "partial",
    [],
    { state: "unknown", warmupBars: 5, seedBars: 2 },
    { state: "partial", warmupBars: -1, seedBars: 2 },
    { state: "partial", warmupBars: 5, seedBars: 2.5 },
    { state: "partial", warmupBars: 5 },
  ]) {
    assert.equal(parseIndicatorSeedState(seed), undefined, JSON.stringify(seed));
    const payload = parseIndicatorPayloadEnvelope({ ok: true, range: { start: 1, end: 2 }, seed });
    assert.equal(payload.seed, undefined, JSON.stringify(seed));
    assert.deepEqual(payload.range, { start: 1, end: 2 });
  }
  assert.deepEqual(parseIndicatorSeedState({ ...converged, extra: true }), converged);
});

test("a partial range is provisional until the convergence warmup is reached", () => {
  const range = { start: 10, end: 100 };
  // warmup 5, seed 2: range bars 0-2 precede convergence, bar 3 converges.
  assert.deepEqual(partialSeedRangeFor(partial, range, [line([10, 20, 30, 40, 50])]), span(10, 30));
  // Too few returned bars: the whole range is provisional.
  assert.deepEqual(partialSeedRangeFor(partial, range, [line([10, 20])]), span(10, 100));
  // Omitted points (undefined values) can only push the end later.
  assert.deepEqual(partialSeedRangeFor(partial, range, [line([20, 30, 40, 50])]), span(10, 40));
  // Outputs share bar times; points outside the range are ignored.
  assert.deepEqual(
    partialSeedRangeFor(partial, range, [line([0, 10, 20]), line([20, 30, 200])]),
    span(10, 30),
  );
  assert.equal(partialSeedRangeFor(converged, range, [line([10, 20])]), null);
  assert.equal(partialSeedRangeFor({ ...partial, seedBars: 5 }, range, [line([10])]), null);
  assert.equal(partialSeedRangeFor(undefined, range, [line([10])]), null);
  assert.equal(partialSeedRangeFor(partial, null, [line([10])]), null);
});

test("a replaced range drops the spans it recomputed and keeps the rest", () => {
  const existing = [span(10, 50), span(100, 150, 0)];
  assert.equal(replacePartialSeedRanges(existing, { start: 60, end: 90 }, null), existing);
  assert.deepEqual(replacePartialSeedRanges(existing, { start: 0, end: 60 }, null), [span(100, 150, 0)]);
  assert.deepEqual(replacePartialSeedRanges(existing, { start: 20, end: 120 }, null), [
    span(10, 19),
    span(121, 150, 0),
  ]);
  assert.deepEqual(replacePartialSeedRanges(existing, { start: 60, end: 90 }, span(60, 70, 1)), [
    span(10, 50),
    span(60, 70, 1),
    span(100, 150, 0),
  ]);
});

test("snapshots reset spans, range replacements replace them, seedless merges keep them", () => {
  const existing = [span(10, 30)];
  const lines = [line([40, 50, 60, 70])];
  assert.deepEqual(updatePartialSeedRanges(existing, "snapshot", { start: 40, end: 70 }, partial, lines), [span(40, 60)]);
  assert.deepEqual(updatePartialSeedRanges(existing, "snapshot", { start: 40, end: 70 }, undefined, lines), []);
  assert.equal(updatePartialSeedRanges(existing, "merge", { start: 10, end: 70 }, undefined, lines), existing);
  assert.deepEqual(updatePartialSeedRanges(existing, "merge", { start: 10, end: 70 }, converged, lines), []);
  assert.deepEqual(updatePartialSeedRanges(existing, "replace-range", { start: 10, end: 30 }, converged, lines), []);
  assert.equal(updatePartialSeedRanges(existing, "replace-range", null, converged, lines), existing);

  const indicator = { id: "ema" };
  assert.equal(withPartialSeed(indicator, []), indicator);
  const marked = withPartialSeed(indicator, existing);
  assert.equal(marked.partialSeed, existing);
  assert.equal(withPartialSeed(marked, existing), marked);
  assert.equal("partialSeed" in withPartialSeed(marked, []), false);

  assert.equal(partialSeedRangeAt(existing, 20), existing[0]);
  assert.equal(partialSeedRangeAt(existing, 31), null);
  assert.equal(partialSeedRangeAt(existing, null), null);
});

const context = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
const ema = { id: "ema-200", engineName: "EMA", script: "# __ENGINE__:EMA", params: { period: 200 } };

function rangePayload(times: readonly number[], seed: unknown) {
  const parsed = parseIndicatorPayloadEnvelope({
    ok: true,
    type: "indicator.replace_range",
    range: { start: times[0], end: times.at(-1) },
    lines: [{ id: "ema", outputName: "ema", data: times.map((time) => ({ time, value: time })) }],
    seed,
  });
  return { parsed, normalized: normalizeParsedIndicatorPayload(parsed, ema.id) };
}

function setupCache() {
  resetIndicatorResultCache();
  resetCacheRegistry();
  registerCacheResource("chart-data-cache", "binance-spot-BTCUSDT-1m", {
    type: "kline",
    dependencyKey: klineDependencyKey(context),
    bars: 100,
  });
}

test("the result cache keeps partial spans per range until they are recomputed", () => {
  setupCache();
  const older = rangePayload([60, 120, 180, 240], { state: "partial", warmupBars: 3, seedBars: 0 });
  const newer = rangePayload([300, 360], { state: "converged", warmupBars: 3, seedBars: 3 });

  cacheIndicatorSnapshot(ema, context, newer.normalized, [], { range: newer.parsed.range ?? null, seed: newer.parsed.seed ?? null });
  assert.equal("partialSeed" in (getCachedIndicatorResult(ema, context) ?? {}), false);

  const stored = replaceCachedIndicatorRange(ema, context, older.normalized, { start: 60, end: 240 }, { seed: older.parsed.seed ?? null });
  const expected = [{ start: 60, end: 180, warmupBars: 3, seedBars: 0 }];
  assert.deepEqual(stored?.partialSeed, expected);
  assert.deepEqual(getCachedIndicatorResult(ema, context)?.partialSeed, expected);
  assert.ok(Object.isFrozen(getCachedIndicatorResult(ema, context)?.partialSeed));

  // A live patch carries no seed and leaves the span alone.
  patchCachedIndicatorResult(ema, context, rangePayload([420], undefined).normalized, { range: { start: 420, end: 420 } });
  assert.deepEqual(getCachedIndicatorResult(ema, context)?.partialSeed, expected);

  // Older history persisted: the same range is recomputed with a converged seed.
  const recomputed = rangePayload([60, 120, 180, 240], { state: "converged", warmupBars: 3, seedBars: 3 });
  replaceCachedIndicatorRange(ema, context, recomputed.normalized, { start: 60, end: 240 }, { seed: recomputed.parsed.seed ?? null });
  assert.equal("partialSeed" in (getCachedIndicatorResult(ema, context) ?? {}), false);
});

test("cached partial spans reach chart lines but never persisted definitions", () => {
  setupCache();
  const short = rangePayload([60, 120, 180], { state: "partial", warmupBars: 2964, seedBars: 0 });
  replaceCachedIndicatorRange(ema, context, short.normalized, { start: 60, end: 180 }, { seed: short.parsed.seed ?? null });
  const cached = getCachedIndicatorResult(ema, context);
  assert.ok(cached);

  const [hydrated] = hydrateIndicatorDefinitionsFromCache([{ ...ema, visible: true, lines: [] }], [cached]);
  assert.ok(hydrated);
  assert.deepEqual(hydrated.partialSeed, [{ start: 60, end: 180, warmupBars: 2964, seedBars: 0 }]);
  assert.equal(hydrateIndicatorDefinitionsFromCache([hydrated], [cached])[0], hydrated);
  assert.equal("partialSeed" in stripIndicatorRuntimeFields(hydrated), false);

  const pane = buildIndicatorPaneData([{ ...hydrated, lines: (hydrated.lines ?? []).map((item) => ({ ...item, pane: "main" })) }]);
  assert.equal(pane.mainOverlayLines[0]?.partialSeed, hydrated.partialSeed);

  const [cleared] = hydrateIndicatorDefinitionsFromCache([hydrated], []);
  assert.equal(cleared && "partialSeed" in cleared, false);
});
