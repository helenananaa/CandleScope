import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import test from "node:test";

import { replayReviewDrawingRecord } from "../../../replay/replayReviewDrawing.js";
import type { DrawingKind, FreehandStrokeV3 } from "../../drawingTypes.js";
import {
  createDrawingDocument,
  createDrawingEntity,
  type DrawingEntityInput,
} from "../drawingDocument.js";
import {
  DRAWING_COMMON_STYLE_KEYS,
  DRAWING_GEOMETRY_KEYS,
  DRAWING_STYLE_KEYS,
} from "../drawingWireContract.js";

const CONTRACT_URL = new URL("../../../../../contracts/drawing-wire.json", import.meta.url);
const SAMPLE_RUN_ID = "wire-contract";
const SAMPLE_CHART_SCOPE = "chart:wire-contract";
const SAMPLE_UPDATED_AT = 1_795_000_000_000;

const at = (time: number, price: number) => ({ time, price });
const common = { hidden: false, locked: true, visibleIntervals: ["1m", "4h"] } as const;
const stroke: FreehandStrokeV3 = {
  version: 3,
  sourceProjection: "renko",
  sourceProjectionConfig: "derived-ordinal:renko:{\"boxSize\":10}",
  spans: [{
    exact: { left: { time: 1_795_000_000, sourceOrdinal: 0 }, right: { time: 1_795_000_060, sourceOrdinal: 1 } },
    fallback: { fromTime: 1_795_000_000, toTime: 1_795_000_060, leftRatio: 0.25, rightRatio: 0.75 },
  }],
  points: [
    { span: 0, ratio: 0.5, price: 60_100.5 },
    { time: 1_795_000_090.5, price: 60_101.25 },
    { anchor: { time: 1_795_000_120, sourceOrdinal: 2 }, price: 60_102 },
  ],
};

/**
 * One entity per drawing kind with every contract key set, built and encoded the
 * way replay training saves them. Freehand and highlighter carry either points or
 * a stroke, never both, and a text is either a callout (target) or a price label,
 * so each appears twice.
 */
const SAMPLES: readonly DrawingEntityInput[] = [
  {
    id: "path-arrow", kind: "path",
    geometry: { kind: "path", dataPoints: [at(1_795_000_000, 60_123.45), at(1_795_000_060, 60_150), at(1_795_000_120, 60_130.5)] },
    style: { kind: "path", arrowEnd: true, color: "#2962ff", lineWidth: 2, ...common },
  },
  {
    id: "channel", kind: "channel",
    geometry: { kind: "channel", dataPoints: [at(1_795_000_000, 60_100), at(1_795_000_120, 60_160), at(1_795_000_060, 60_090.5)] },
    style: { kind: "channel", color: "#089981", fillOpacity: 0.15, lineWidth: 1, ...common },
  },
  {
    id: "range-measure", kind: "range-measure",
    geometry: { kind: "range-measure", measureType: "price-time", dataPoints: [at(1_795_000_000, 60_100), at(1_795_000_180, 60_180.75)] },
    style: { kind: "range-measure", color: "#2962ff", lineWidth: 1, ...common },
  },
  {
    id: "line-arrow", kind: "line",
    geometry: { kind: "line", lineType: "line-segment", dataPoints: [at(1_795_000_000, 60_100), at(1_795_000_060, 60_110)] },
    style: { kind: "line", arrowEnd: true, color: "#f23645", lineWidth: 2, ...common },
  },
  {
    id: "axis-line", kind: "axis-line",
    geometry: { kind: "axis-line", axisLineType: "horizontal", dataPoint: at(1_795_000_000, 60_120.5) },
    style: { kind: "axis-line", color: "#787b86", lineWidth: 1, ...common },
  },
  {
    id: "angle-measure", kind: "angle-measure",
    geometry: { kind: "angle-measure", dataPoints: [at(1_795_000_000, 60_100), at(1_795_000_060, 60_140)] },
    style: { kind: "angle-measure", color: "#787b86", lineWidth: 1, ...common },
  },
  {
    id: "callout", kind: "text",
    geometry: { kind: "text", dataPoint: at(1_795_000_000, 60_100), target: at(1_795_000_060, 60_120.5) },
    style: {
      kind: "text", text: "Note", color: "#131722", fontSize: 14, fontFamily: "Inter", bold: true,
      italic: true, underline: true, align: "center", bgColor: "#ffffff", borderColor: "#2962ff",
      borderWidth: 1, widthPx: 160, padding: 6, ...common,
    },
  },
  {
    id: "price-label", kind: "text",
    geometry: { kind: "text", dataPoint: at(1_795_000_120, 60_133.25) },
    style: { kind: "text", text: "", priceLabel: true, color: "#2962ff" },
  },
  {
    id: "fibonacci", kind: "fibonacci",
    geometry: { kind: "fibonacci", dataPoints: [at(1_795_000_000, 60_000), at(1_795_000_120, 60_200)], inverted: true },
    style: {
      kind: "fibonacci", color: "#787b86", lineWidth: 1,
      levels: [{ level: 0, color: "#787b86", enabled: true }, { level: 0.618, color: "#2962ff", enabled: true }],
      ...common,
    },
  },
  {
    id: "position", kind: "position",
    geometry: {
      kind: "position", direction: "long", entryPrice: 60_100.5, tpPrice: 60_300, slPrice: 60_000,
      timeRange: { start: { time: 1_795_000_000 }, end: { time: 1_795_000_600 } },
    },
    style: { kind: "position", positionSize: 0.25, infoPanelOffset: { anchor: "right", x: 12, y: -8 }, ...common },
  },
  {
    id: "zone", kind: "shape",
    geometry: { kind: "shape", shapeType: "rectangle", dataPoints: [at(1_795_000_000, 60_100), at(1_795_000_120, 60_150)], extendRight: true },
    style: {
      kind: "shape", color: "#2962ff", lineWidth: 1, fillColor: "#2962ff", fillOpacity: 0.2,
      lineStyle: "dashed", midline: true, priceLabels: true, label: "Demand", ...common,
    },
  },
  {
    id: "pen-points", kind: "freehand",
    geometry: { kind: "freehand", dataPoints: [at(1_795_000_000, 60_100), at(1_795_000_030, 60_105.5)] },
    style: { kind: "freehand", color: "#131722", lineWidth: 2, ...common },
  },
  {
    id: "pen-stroke", kind: "freehand",
    geometry: { kind: "freehand", stroke },
    style: { kind: "freehand", color: "#131722", lineWidth: 2 },
  },
  {
    id: "highlighter-points", kind: "highlighter",
    geometry: { kind: "highlighter", dataPoints: [at(1_795_000_000, 60_100), at(1_795_000_030, 60_105.5)] },
    style: {
      kind: "highlighter", color: "#ffeb3b", lineWidth: 12, opacity: 0.4,
      compositeOperation: "multiply", brushShape: "square", ...common,
    },
  },
  {
    id: "highlighter-stroke", kind: "highlighter",
    geometry: { kind: "highlighter", stroke },
    style: { kind: "highlighter", color: "#ffeb3b", lineWidth: 12 },
  },
];

function sortedKeys(value: unknown): string[] {
  return Object.keys(value as Record<string, unknown>).sort();
}

function replaySaveSample(): Record<string, unknown> {
  const entities = SAMPLES.map(createDrawingEntity);
  const document = createDrawingDocument({
    scopeKey: SAMPLE_CHART_SCOPE,
    entities,
    zOrder: entities.map((entity) => entity.id),
  });
  // Same shape as useReplayWorkspaceDrawings.flush: a v2 workspace of v1 chart records.
  return {
    documentSchemaVersion: 2,
    scopeKey: `replay-run:${SAMPLE_RUN_ID}`,
    charts: { [SAMPLE_CHART_SCOPE]: replayReviewDrawingRecord(document, SAMPLE_RUN_ID, SAMPLE_UPDATED_AT) },
  };
}

function expectedContract(): Record<string, unknown> {
  const kinds = Object.keys(DRAWING_GEOMETRY_KEYS).sort() as DrawingKind[];
  return {
    contract: "candlescope.drawing-wire.v1",
    source: "frontend/src/features/drawings/core/drawingWireContract.ts",
    regenerate: "UPDATE_DRAWING_WIRE_CONTRACT=1 node scripts/run-frontend-tests.mjs "
      + "src/features/drawings/core/__tests__/drawingWireContract.test.ts",
    commonStyleKeys: [...DRAWING_COMMON_STYLE_KEYS].sort(),
    kinds: Object.fromEntries(kinds.map((kind) => [kind, {
      geometry: [...DRAWING_GEOMETRY_KEYS[kind]].sort(),
      style: [...DRAWING_STYLE_KEYS[kind]].sort(),
    }])),
    replaySample: {
      runId: SAMPLE_RUN_ID,
      entityCount: SAMPLES.length,
      document: replaySaveSample(),
    },
  };
}

test("the replay save sample sets every contract key for every drawing kind", () => {
  const seenGeometry = new Map<string, Set<string>>();
  const seenStyle = new Map<string, Set<string>>();
  const chart = (replaySaveSample().charts as Record<string, { entities: Record<string, unknown>[] }>)[SAMPLE_CHART_SCOPE];
  assert.equal(chart?.entities.length, SAMPLES.length);
  for (const entity of chart.entities) {
    const kind = entity.kind as string;
    for (const key of sortedKeys(entity.geometry)) (seenGeometry.get(kind) ?? seenGeometry.set(kind, new Set()).get(kind)!).add(key);
    for (const key of sortedKeys(entity.style)) (seenStyle.get(kind) ?? seenStyle.set(kind, new Set()).get(kind)!).add(key);
  }
  for (const kind of Object.keys(DRAWING_GEOMETRY_KEYS) as DrawingKind[]) {
    assert.deepEqual([...(seenGeometry.get(kind) ?? [])].sort(), [...DRAWING_GEOMETRY_KEYS[kind]].sort(), `${kind} geometry`);
    assert.deepEqual(
      [...(seenStyle.get(kind) ?? [])].sort(),
      [...DRAWING_STYLE_KEYS[kind], ...DRAWING_COMMON_STYLE_KEYS].sort(),
      `${kind} style`,
    );
  }
});

test("the canonical validator accepts exactly the contract keys", () => {
  for (const kind of Object.keys(DRAWING_GEOMETRY_KEYS) as DrawingKind[]) {
    const sample = SAMPLES.find((candidate) => candidate.kind === kind)!;
    assert.throws(
      () => createDrawingEntity({ ...sample, geometry: { ...sample.geometry, unexpected: 1 } as never }),
      TypeError,
      `${kind} geometry must reject keys outside the contract`,
    );
    assert.throws(
      () => createDrawingEntity({ ...sample, style: { ...sample.style, unexpected: 1 } as never }),
      TypeError,
      `${kind} style must reject keys outside the contract`,
    );
  }
});

test("contracts/drawing-wire.json mirrors the contract for the backend allowlist test", () => {
  const expected = expectedContract();
  if (process.env.UPDATE_DRAWING_WIRE_CONTRACT === "1") {
    writeFileSync(CONTRACT_URL, `${JSON.stringify(expected, null, 2)}\n`);
  }
  const actual = JSON.parse(readFileSync(CONTRACT_URL, "utf8")) as unknown;
  assert.deepEqual(actual, expected, `contracts/drawing-wire.json is stale; run: ${String(expected.regenerate)}`);
});
