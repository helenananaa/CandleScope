import assert from "node:assert/strict";
import test from "node:test";
import { replayChartNotePoints, replayChartNoteVersions } from "../replayChartNoteOverlay.js";
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
  const points = replayChartNotePoints([earlier, note, reviewNote], "5m", time => time === at / 1_000,
    supplement => supplement ? "Review supplement" : "Replay notes");
  assert.deepEqual(points.map(({ id, revision, text, time }) => ({ id, revision, text, time })), [
    { id: "plan", revision: 1, text: "Replay notes", time: at / 1_000 },
    { id: "supplement", revision: 2, text: "Review supplement", time: at / 1_000 },
  ]);
});
