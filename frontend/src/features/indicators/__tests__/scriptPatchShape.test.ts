import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

import { klineDependencyKey, registerCacheResource, resetCacheRegistry } from "../../cache-gc/cacheRegistry.js";
import { createIndicatorOutputState, indicatorOutputReducer } from "../indicatorOutputReducer.js";
import { mergeIndicatorLines, normalizeIndicatorPayload } from "../indicatorPayloadRuntime.js";
import {
  cacheIndicatorSnapshot,
  getCachedIndicatorResult,
  patchCachedIndicatorResult,
  resetIndicatorResultCache,
} from "../indicatorResultCacheStore.js";
import { parseIndicatorWsMessage } from "../indicatorWsRuntime.js";

type WireRecord = Record<string, unknown>;

// Frozen backend output: a Pine-shaped subscription snapshot over six closed
// bars, then the live `indicator.patch` for the forming seventh bar.
const { snapshot, patch } = JSON.parse(readFileSync(resolve(
  process.cwd(),
  "../backend/tests/fixtures/plugin_runtime/script-live-patch.json",
), "utf8")) as { snapshot: WireRecord; patch: WireRecord };

const indicator = { id: "pine-rich", script: "//@version=6", language: "pine" };
const context = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };

function records(message: WireRecord, key: string): WireRecord[] {
  return message[key] as WireRecord[];
}

/** The same tick as the stream sent it before trimming: full-history script fields. */
function fullHistoryPatch(): WireRecord {
  const joined = (before: WireRecord | undefined, tick: WireRecord, field: string) => [
    ...(before?.[field] as unknown[]),
    ...(tick[field] as unknown[]),
  ];
  return {
    ...patch,
    result: snapshot.result,
    legacyFills: records(patch, "legacyFills").map((fill, index) => ({
      ...fill,
      colorData: joined(records(snapshot, "legacyFills")[index], fill, "colorData"),
    })),
    bgcolors: records(patch, "bgcolors").map((bgcolor, index) => ({
      ...bgcolor,
      regions: joined(records(snapshot, "bgcolors")[index], bgcolor, "regions"),
    })),
  };
}

function parsed(message: WireRecord) {
  const result = parseIndicatorWsMessage(JSON.stringify(message));
  if (!result.ok) throw result.error;
  return result.message;
}

function normalized(message: WireRecord) {
  return normalizeIndicatorPayload(parsed(message), indicator.id);
}

function renderedAfter(tick: WireRecord) {
  const base = normalized(snapshot);
  const next = normalized(tick);
  let state = indicatorOutputReducer(createIndicatorOutputState(), {
    type: "snapshot",
    indicatorId: indicator.id,
    normalized: base,
    schema: [],
  });
  state = indicatorOutputReducer(state, { type: "patch", indicatorId: indicator.id, normalized: next });
  return { lines: mergeIndicatorLines(base.lines, next.lines), state };
}

function cachedAfter(tick: WireRecord) {
  resetIndicatorResultCache();
  resetCacheRegistry();
  registerCacheResource("chart-data-cache", "binance-spot-BTCUSDT-1m", {
    type: "kline",
    dependencyKey: klineDependencyKey(context),
    bars: 7,
  });
  cacheIndicatorSnapshot(indicator, context, normalized(snapshot), [], {
    range: snapshot.range as { start: number; end: number },
  });
  patchCachedIndicatorResult(indicator, context, normalized(tick), {
    range: tick.range as { start: number; end: number },
  });
  return getCachedIndicatorResult(indicator, context)?.normalized;
}

test("live script patches leave out the nested Render IR the browser never reads", () => {
  assert.equal(patch.type, "indicator.patch");
  assert.equal(patch.reason, "bar_update");
  assert.ok(snapshot.result);
  assert.equal("result" in patch, false);
  for (const message of [snapshot, patch, fullHistoryPatch()]) {
    assert.equal("result" in parsed(message), false);
  }
});

test("a trimmed live script patch renders exactly like the full-history patch", () => {
  const trimmed = renderedAfter(patch);

  assert.deepEqual(trimmed, renderedAfter(fullHistoryPatch()));
  assert.deepEqual(trimmed.lines.map((line) => line.data.length), [7, 7]);
  assert.equal(trimmed.state.drawings?.[0]?.times.length, 7);
  const cached = cachedAfter(patch);
  assert.deepEqual(cached?.lines.map((line) => line.data.length), [7, 7]);
  assert.deepEqual(cached, cachedAfter(fullHistoryPatch()));
});

test("live script patches must carry whole drawing scenes", () => {
  assert.deepEqual(
    renderedAfter(patch).state.drawings,
    records(patch, "drawings").map((scene) => ({ ...scene, indicatorId: indicator.id })),
  );

  // A patch scene replaces the previous one, and an absent scene removes the
  // lane, so the stream cannot slice or skip drawings on a live tick.
  const { drawings: _drawings, ...withoutDrawings } = patch;
  assert.deepEqual(renderedAfter(withoutDrawings).state.drawings, []);
});
