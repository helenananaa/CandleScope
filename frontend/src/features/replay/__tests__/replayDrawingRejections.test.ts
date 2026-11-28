import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  excludeRejectedDrawings,
  replayDrawingSaveDocument,
  replayRejectedDrawings,
  replayRejectedDrawingsMessage,
  type ReplayDrawingExclusions,
} from "../replayDrawingRejections.js";
import { ReplayV2ApiError } from "../replayV2Api.js";

function entity(id: string, kind = "line", geometryRevision = 1, styleRevision = 1) {
  return { id, kind, geometryRevision, styleRevision, geometry: { kind }, style: { kind }, bounds: { kind: "deferred" } };
}

function chart(...entities: ReturnType<typeof entity>[]) {
  return { documentSchemaVersion: 1, scopeKey: "replay-run:run", documentRevision: 4, updatedAt: 1, entities };
}

function rejection(rejected: unknown, code = "REVIEW_DRAWING_INVALID") {
  return new ReplayV2ApiError(code, "drawing document is not a bounded run-scoped canonical record", {
    status: 422,
    details: { rejected, rejected_count: Array.isArray(rejected) ? rejected.length : 0 },
  });
}

test("only a REVIEW_DRAWING_INVALID response that names charted drawings is read", () => {
  assert.equal(replayRejectedDrawings(new Error("network")), null);
  assert.equal(replayRejectedDrawings(rejection([{ chart: "a", id: "x", reason: "INVALID" }], "REVIEW_DRAWING_HASH_MISMATCH")), null);
  assert.equal(replayRejectedDrawings(rejection([])), null);
  assert.equal(replayRejectedDrawings(rejection(undefined)), null);
  // A legacy single-chart record has no chart scope to leave the drawing out of.
  assert.equal(replayRejectedDrawings(rejection([{ chart: null, id: "x", kind: "line", reason: "INVALID" }])), null);
  assert.deepEqual(replayRejectedDrawings(rejection([
    { chart: "btc__main", id: "path-1", kind: "path", reason: "UNSUPPORTED_KIND", fields: [] },
    { chart: "btc__main", id: "odd", kind: null, reason: "SOMETHING_NEW", fields: [] },
  ])), [
    { chart: "btc__main", id: "path-1", kind: "path", reason: "UNSUPPORTED_KIND" },
    { chart: "btc__main", id: "odd", kind: null, reason: "INVALID" },
  ]);
});

test("a rejected drawing is left out and the others are saved", () => {
  const charts = { btc: chart(entity("segment"), entity("path-1", "path")), eth: chart(entity("text", "text")) };
  const exclusions: ReplayDrawingExclusions = new Map();
  const named = replayRejectedDrawings(rejection([{ chart: "btc", id: "path-1", kind: "path", reason: "UNSUPPORTED_KIND" }]))!;
  assert.equal(excludeRejectedDrawings(exclusions, charts, named), 1);
  // Naming the same drawing at the same revision again is no progress, so the save loop stops.
  assert.equal(excludeRejectedDrawings(exclusions, charts, named), 0);

  const save = replayDrawingSaveDocument("run", charts, exclusions);
  assert.equal(save.count, 2);
  assert.deepEqual(save.document.charts.btc!.entities, [entity("segment")]);
  assert.equal(save.document.charts.eth, charts.eth, "untouched charts are sent as they are");
  assert.deepEqual(save.excluded, [{ chart: "btc", id: "path-1", kind: "path", reason: "UNSUPPORTED_KIND", variant: "path-line" }]);
  assert.deepEqual(charts.btc.entities.map(({ id }) => id), ["segment", "path-1"], "the chart itself keeps the drawing");
});

test("editing or deleting a left-out drawing offers it again", () => {
  const exclusions: ReplayDrawingExclusions = new Map();
  const named = [{ chart: "btc", id: "path-1", kind: "path", reason: "UNSUPPORTED_FIELD" } as const];
  excludeRejectedDrawings(exclusions, { btc: chart(entity("path-1", "path")) }, named);

  const edited = replayDrawingSaveDocument("run", { btc: chart(entity("path-1", "path", 1, 2)) }, exclusions);
  assert.equal(edited.count, 1);
  assert.deepEqual(edited.excluded, []);
  assert.equal(exclusions.size, 0);

  excludeRejectedDrawings(exclusions, { btc: chart(entity("path-1", "path")) }, named);
  const deleted = replayDrawingSaveDocument("run", { btc: chart(entity("segment")) }, exclusions);
  assert.equal(deleted.count, 1);
  assert.deepEqual(deleted.excluded, []);
});

test("a drawing the response names but the chart no longer holds is not progress", () => {
  const exclusions: ReplayDrawingExclusions = new Map();
  assert.equal(excludeRejectedDrawings(exclusions, { btc: chart(entity("segment")) }, [
    { chart: "btc", id: "gone", kind: "line", reason: "INVALID" },
    { chart: "missing-chart", id: "segment", kind: "line", reason: "INVALID" },
  ]), 0);
});

test("left-out drawings are named like the drawing object list names them", () => {
  const arrowPath = { ...entity("arrow", "path"), style: { kind: "path", arrowEnd: true } };
  const range = { ...entity("range", "range-measure"), geometry: { kind: "range-measure", measureType: "price" } };
  const ray = { ...entity("ray"), geometry: { kind: "line", lineType: "line-ray" } };
  const exclusions: ReplayDrawingExclusions = new Map();
  excludeRejectedDrawings(exclusions, { btc: chart(arrowPath, range, ray) }, ["arrow", "range", "ray"].map((id) => (
    { chart: "btc", id, kind: null, reason: "UNSUPPORTED_FIELD" as const })));
  assert.deepEqual([...exclusions.values()].map(({ variant }) => variant), ["path-arrow", "measure-price", "line-ray"]);
});

test("the notice names each left-out drawing once, with how many, and why", () => {
  const message = replayRejectedDrawingsMessage([
    { chart: "btc", id: "a", kind: "path", reason: "UNSUPPORTED_KIND" },
    { chart: "btc", id: "b", kind: "path", reason: "UNSUPPORTED_KIND" },
    { chart: "eth", id: "c", kind: null, reason: "INVALID" },
  ]);
  assert.match(message, /\(2\)/);
  assert.match(message, /\bc\b/);
  assert.ok(message.length > 40);
});

test("the replay save hook saves through the exclusion helpers and shows the notice", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const hook = readFileSync(resolve(here, "../useReplayWorkspaceDrawings.ts"), "utf8");
  assert.match(hook, /replayDrawingSaveDocument\(runId, snapshot, exclusions\.current\)/);
  assert.match(hook, /excludeRejectedDrawings\(exclusions\.current, snapshot, named\) > 0\) continue;/);
  assert.match(hook, /return \{ error, rejected, retry: flush \};/);
  const workspace = readFileSync(resolve(here, "../ReplayChartWorkspace.tsx"), "utf8");
  assert.match(workspace, /replayRejectedDrawingsMessage\(drawings\.rejected\)/);
});
