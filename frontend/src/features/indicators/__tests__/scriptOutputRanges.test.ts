import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

import { klineDependencyKey, registerCacheResource, resetCacheRegistry } from "../../cache-gc/cacheRegistry.js";
import { createIndicatorOutputState, indicatorOutputReducer } from "../indicatorOutputReducer.js";
import { normalizeIndicatorPayload, replaceIndicatorLinesRange } from "../indicatorPayloadRuntime.js";
import { cacheIndicatorSnapshot, getCachedIndicatorResult, replaceCachedIndicatorRange, resetIndicatorResultCache } from "../indicatorResultCacheStore.js";
import { dispatchIndicatorWsMessage, parseIndicatorWsMessage } from "../indicatorWsRuntime.js";
import type { IndicatorLine } from "../indicatorTypes.js";

type Wire = Record<string, unknown>;
interface Fixture { id: string; source: string; sourceBarTime: number; changedDisplayTime: number; snapshot: Wire; update: Wire; expected: Wire }
const fixtures = JSON.parse(readFileSync(resolve(process.cwd(), "../backend/tests/fixtures/plugin_runtime/script-output-ranges.json"), "utf8")) as { cases: Fixture[] };
const context = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
function parsed(wire: Wire) {
  const result = parseIndicatorWsMessage(JSON.stringify(wire));
  if (!result.ok) throw result.error;
  return result.message;
}
function semanticLines(lines: IndicatorLine[]) {
  return lines.map(({ renderUpdate: _hint, ...line }) => { void _hint; return line; });
}

for (const fixture of fixtures.cases) test(`real Pine output range adopts ${fixture.id} in renderer and cache`, () => {
  resetIndicatorResultCache(); resetCacheRegistry();
  registerCacheResource("chart-data-cache", "binance-spot-BTCUSDT-1m", { type: "kline", dependencyKey: klineDependencyKey(context), bars: 22 });
  const indicator = { id: fixture.id, script: fixture.source, language: "pine" };
  let state = createIndicatorOutputState(); let lines: IndicatorLine[] = [];
  for (const wire of [fixture.snapshot, fixture.update]) {
    const message = parsed(wire);
    assert.equal(dispatchIndicatorWsMessage(message, {
      onSnapshot: (id, payload) => {
        assert.equal(id, indicator.id);
        const normalized = normalizeIndicatorPayload(payload, id);
        lines = normalized.lines;
        state = indicatorOutputReducer(state, { type: "snapshot", indicatorId: id, normalized, schema: [] });
        const range = payload.range;
        assert.ok(range);
        cacheIndicatorSnapshot(indicator, context, normalized, [], { range });
      },
      onReplaceRange: (id, payload) => {
        assert.equal(id, indicator.id);
        const normalized = normalizeIndicatorPayload(payload, id);
        lines = replaceIndicatorLinesRange(lines, normalized.lines, payload.range);
        state = indicatorOutputReducer(state, { type: "replace-range", indicatorId: id, normalized, range: payload.range });
        replaceCachedIndicatorRange(indicator, context, normalized, payload.range);
      },
    }), true);
  }
  const expected = normalizeIndicatorPayload(parsed(fixture.expected), indicator.id);
  const reference = indicatorOutputReducer(createIndicatorOutputState(), { type: "snapshot", indicatorId: indicator.id, normalized: expected, schema: [] });
  assert.deepEqual(semanticLines(lines), semanticLines(expected.lines));
  assert.deepEqual(state, reference);
  const cached = getCachedIndicatorResult(indicator, context)?.normalized;
  assert.ok(cached);
  assert.deepEqual(semanticLines(cached.lines), semanticLines(expected.lines));
  for (const field of ["markers", "bgcolors", "barcolors", "hlines", "fills", "signals", "drawings"] as const) assert.deepEqual(cached[field] ?? [], expected[field] ?? []);

  if (fixture.id.startsWith("negative-")) {
    assert.equal(fixture.update.type, "indicator.replace_range");
    assert.ok(fixture.changedDisplayTime < fixture.sourceBarTime - 60, "Fixture has a real time gap; interval subtraction is wrong");
  }
  if (fixture.id === "negative-line") assert.equal(lines[0]?.data.find(point => point.time === fixture.changedDisplayTime)?.value, 104);
  if (fixture.id === "negative-na") assert.ok(lines.every(line => line.data.length === 0), "The former point is removed when Pine returns na");
  if (fixture.id === "negative-markers") assert.equal(state.markers[0]?.data?.length, 19);
  if (fixture.id === "negative-bgcolor") assert.equal(state.bgcolors[0]?.regions?.length, 19);
  if (fixture.id === "remove-last-marker") assert.equal(state.markers.length, 0);
  if (fixture.id === "history-correction") assert.equal(lines[0]?.data.find(point => point.time === 1_700_000_000 + 4 * 120)?.value, 130);
  if (fixture.id === "show-last") {
    assert.equal(lines[0]?.data.length, 3);
    assert.ok(lines[0]?.data.every(point => point.time !== 1_700_000_000 + 17 * 120), "Old show_last point is removed by the snapshot");
  }
});
