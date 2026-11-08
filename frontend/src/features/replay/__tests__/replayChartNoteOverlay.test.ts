import assert from "node:assert/strict";
import test from "node:test";
import { replayChartNotePoints, replayChartNoteVersions, type ReplayChartNoteFilter } from "../replayChartAnnotations.js";
import type { ReplayNote, ReplayNotesResponse } from "../replayNotes.js";

const at = 1_700_000_400_000;
const binding = { runId: "run", trackId: "btc", dataEpoch: "btc-epoch", reviewId: "review",
  reviewRevision: 2, timelineSequence: 12 };
const note: ReplayNote = { id: "plan", runId: "run", trackId: "btc", marketTimeMs: at + 25_000,
  effectiveTimeMs: at + 25_000, createdAtMs: at, updatedAtMs: at, revisionCount: 1,
  timelineSequence: 11, fields: { entryBasis: "original" }, body: "", reviewNote: false, revisions: [] };
const response: ReplayNotesResponse = {
  protocol: "replay.v3", schema_version: "replay.notes.v1", run_id: "run", track_id: "btc",
  asOfMs: at + 30_000, notes: [note],
  context: { ...binding, virtualTimeMs: at + 30_000, runRevision: 10, sourceSequence: 8,
    checkpointSequence: 8, reviewNote: true },
};

test("formal chart notes reject newer time, another track or epoch, and a different Review event at the same time", () => {
  assert.deepEqual(replayChartNoteVersions(response, binding, at + 30_000), [note]);
  assert.deepEqual(replayChartNoteVersions(response, binding, at + 29_999), []);
  for (const override of [
    { runId: "other" }, { trackId: "eth" }, { dataEpoch: "old" }, { timelineSequence: 11 }, { reviewRevision: 1 },
  ]) {
    assert.deepEqual(replayChartNoteVersions(response, { ...binding, ...override }, at + 30_000), []);
  }
});

test("note versions land on loaded display buckets without copying note text into markers", () => {
  const earlier = { ...note, id: "unloaded", marketTimeMs: at - 600_000 };
  const reviewNote = { ...note, id: "supplement", revisionCount: 2, reviewNote: true };
  const points = replayChartNotePoints([earlier, note, reviewNote], "5m", true, time => time === at / 1_000,
    supplement => supplement ? "Review supplement" : "Replay notes");
  assert.deepEqual(points.map(({ id, revision, text, time }) => ({ id, revision, text, time })), [
    { id: "plan", revision: 1, text: "Replay notes", time: at / 1_000 },
    { id: "supplement", revision: 2, text: "Review supplement", time: at / 1_000 },
  ]);
});

test("a note saved at a BAR close stays on the closed candle after the next candle opens", () => {
  const atClose = { ...note, marketTimeMs: at };
  const positions = (closedBarClock: boolean) =>
    replayChartNotePoints([atClose], "5m", closedBarClock, () => true, () => "Notes").map(point => point.time);
  assert.deepEqual(positions(true), [at / 1_000 - 300]);
  assert.deepEqual(positions(false), [at / 1_000]);
});

test("note filters match only the revealed version's source and attachments", () => {
  const linked: ReplayNote = { ...note, revisionCount: 2, links: [{
    kind: "FILL", id: "fill", fillId: "fill", eventTimeMs: at, sourceSequence: 2,
    side: "BUY", quantity: "0.1", price: "100",
  }] };
  const supplement: ReplayNote = { ...note, id: "supplement", reviewNote: true, screenshots: [{
    id: "image", runId: "run", trackId: "btc", dataEpoch: "btc-epoch", marketTimeMs: at,
    timelineSequence: 11, savedAtMs: at, width: 1, height: 1, interval: "5m", chartType: "candles",
  }] };
  const markers = (versions: ReplayNote[], filter: ReplayChartNoteFilter) =>
    replayChartNotePoints(versions, "5m", true, () => true, () => "Notes", filter).map(point => [point.id, point.revision]);
  assert.deepEqual(markers([note, supplement], { noteFilter: "linked" }), []);
  assert.deepEqual(markers([linked, supplement], { noteSource: "original", noteFilter: "linked" }), [["plan", 2]]);
  assert.deepEqual(markers([linked, supplement], { noteSource: "review", noteFilter: "screenshots" }), [["supplement", 1]]);
  assert.deepEqual(markers([linked, supplement], { noteSource: "original", noteFilter: "screenshots" }), []);
});
