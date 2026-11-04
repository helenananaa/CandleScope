import assert from "node:assert/strict";
import test from "node:test";
import { attachReplayNoteCapture, copyReplayNoteCaptureDraft, createReplayNoteCaptureDraft, readReplayNoteCaptureDraft,
  releaseReplayNoteCaptureDraft, replayNoteScreenshotIds, saveReplayNoteCaptureDraft } from "../replayNoteCaptureDraft.js";
import { parseReplayNoteImageResponse, parseReplayNotesResponse, type ReplayNoteContext } from "../replayNotes.js";
import { ReplayDataManager } from "../replayDataManager.js";
import { managedReplayRunApi } from "../managedReplayTransport.js";
import { captureReplayNoteChart } from "../replayNoteChartCapture.js";
import { ReplayV2ApiClient } from "../replayV2Api.js";
const context = (time = 100, sequence = 1): ReplayNoteContext => ({ runId: "run", trackId: "track", dataEpoch: "epoch",
  runRevision: sequence, sourceSequence: sequence, checkpointSequence: 0, timelineSequence: sequence, virtualTimeMs: time,
  reviewId: null, reviewRevision: null, reviewNote: false });
const image = "data:image/png;base64,iVBORw0KGgo=";
const chart = { interval: "1m", chartType: "candles", seriesKey: "run:track:epoch", sourceVersion: 1 };
class Storage {
  values = new Map<string, string>();
  getItem(key: string) { return this.values.get(key) ?? null; }
  setItem(key: string, value: string) { this.values.set(key, value); }
  removeItem(key: string) { this.values.delete(key); }
}
const capture = () => ({ id: "image", runId: "run", trackId: "track", dataEpoch: "epoch", marketTimeMs: 100,
  timelineSequence: 1, savedAtMs: 1000, width: 1, height: 1, interval: "1m", chartType: "candles" });
const response = () => ({ protocol: "replay.v3", schema_version: "replay.note-image.v1", context: context(),
  note_id: "note", revision: 1, capture: capture(), image });

test("PNG request survives restart exactly, preserves original on explicit copy, and never opens in a past or foreign view", () => {
  const storage = new Storage(), original = createReplayNoteCaptureDraft(context(), { image, capturedContext: context(), chart });
  saveReplayNoteCaptureDraft(storage, original);
  const old = new Map(storage.values);
  assert.deepEqual(readReplayNoteCaptureDraft(storage, original.id, context(), context(200, 2)), original);
  assert.throws(() => readReplayNoteCaptureDraft(storage, original.id, context(), context(50, 0)));
  assert.throws(() => readReplayNoteCaptureDraft(storage, original.id, { ...context(), trackId: "other" }, context()));
  assert.deepEqual(storage.values, old);
  const fields = { entryBasis: "retained text", replayPendingCaptureId: original.id };
  const current = context(200, 2), copied = copyReplayNoteCaptureDraft(storage, fields, context(), current);
  assert.notEqual(copied.replayPendingCaptureId, original.id);
  const copy = readReplayNoteCaptureDraft(storage, copied.replayPendingCaptureId!, current, current)!;
  assert.equal(copy.image, image); assert.deepEqual(copy.capturedContext, original.capturedContext); assert.deepEqual(copy.context, current);
  assert.equal([...storage.values.values()].filter(value => value === [...old.values()][0]).length, 1);
  assert.throws(() => copyReplayNoteCaptureDraft(storage, fields, context(), context(50, 0)));
  assert.throws(() => saveReplayNoteCaptureDraft(storage, { ...original, image: "data:image/png;base64,AAAA" }));
  releaseReplayNoteCaptureDraft(storage, copy); assert.deepEqual(storage.values, old);
});

test("completed image attaches only to its own pending draft and keeps later text edits", () => {
  const fields = { entryBasis: "edited while upload was in flight", replayPendingCaptureId: "image", replayScreenshotIds: '["old"]' };
  const attached = attachReplayNoteCapture(fields, "image");
  assert.equal(attached.entryBasis, fields.entryBasis); assert.equal(attached.replayPendingCaptureId, undefined);
  assert.deepEqual(replayNoteScreenshotIds(attached), ["old", "image"]);
  assert.throws(() => attachReplayNoteCapture(fields, "different-pending"));
  assert.throws(() => attachReplayNoteCapture({ ...fields, replayScreenshotIds: '["old","another"]' }, "image"));
  assert.throws(() => replayNoteScreenshotIds({ replayScreenshotIds: '["same","same"]' }));
});

test("image parser rejects future pixels metadata, non-PNG URLs, excessive dimensions and cross-epoch note images", () => {
  assert.equal(parseReplayNoteImageResponse(response()).image, image);
  for (const invalid of [{ capture: { ...capture(), marketTimeMs: 101 } }, { capture: { ...capture(), timelineSequence: 2 } },
    { capture: { ...capture(), width: 4097 } }, { image: "https://untrusted.invalid/image.png" }, { image: "data:image/svg+xml;base64,AAAA" }])
    assert.throws(() => parseReplayNoteImageResponse({ ...response(), ...invalid }));
  const note = { id: "note", runId: "run", trackId: "track", marketTimeMs: 100, effectiveTimeMs: 100, createdAtMs: 1000,
    updatedAtMs: 1000, revisionCount: 1, timelineSequence: 1, fields: { replayScreenshotIds: '["image"]' }, body: "", reviewNote: false, revisions: [], screenshots: [capture()] };
  const notes = { protocol: "replay.v3", schema_version: "replay.notes.v1", run_id: "run", track_id: "track", context: context(), asOfMs: 100, notes: [note] };
  assert.equal(parseReplayNotesResponse(notes).notes[0]!.screenshots!.length, 1);
  assert.throws(() => parseReplayNotesResponse({ ...notes, notes: [{ ...note, screenshots: [{ ...capture(), dataEpoch: "different" }] }] }));
});

test("parsed PNG body remains cancellable under the manager lease; wrong note version cannot replace it", async () => {
  const manager = new ReplayDataManager(), lease = manager.createOperations({ runId: "run", purpose: "review" }), release = lease.retain();
  let complete!: (value: string) => void;
  const api = new ReplayV2ApiClient({ fetcher: async () => { const value = new Response();
    value.text = () => new Promise(resolve => { complete = resolve; }); return value; } });
  const pending = managedReplayRunApi(lease, api).noteScreenshotRun("run", "track", "note", 1, "image");
  await Promise.resolve(); assert.equal(manager.diagnostics().requests, 1);
  const rejected = assert.rejects(pending, { name: "AbortError" }); release(); await rejected; complete(JSON.stringify(response()));
  assert.equal(manager.diagnostics().requests, 0); manager.dispose();
  const wrong = new ReplayV2ApiClient({ fetcher: async () => Response.json({ ...response(), revision: 2 }) });
  await assert.rejects(wrong.noteScreenshotRun("run", "track", "note", 1, "image"));
});


test("chart capture refuses a changed source before preparing drawings and restores a stale painted-source lease", async () => {
  const previous = globalThis.requestAnimationFrame;
  globalThis.requestAnimationFrame = callback => { queueMicrotask(() => callback(0)); return 1; };
  try {
    const source = { ready: true, seriesKey: "series", sourceVersion: 1, interval: "1m", chartType: "candles", contextKey: "context" };
    let prepared = 0, restored = 0, reads = 0;
    const surface = { prepareExport: async () => { prepared++; return null; }, getExportSnapshot: () => null };
    await assert.rejects(captureReplayNoteChart(surface, context(), () => ({ ...source, sourceVersion: ++reads })));
    assert.equal(prepared, 0);
    const leaseSurface = { prepareExport: async () => { prepared++; return { revalidate: async () => true, restore: async () => { restored++; } } as never; },
      getExportSnapshot: () => ({ rootElement: {} as HTMLElement, sourceWindow: { seriesKey: "series", version: 1, current: false } }) };
    await assert.rejects(captureReplayNoteChart(leaseSurface, context(), () => source));
    assert.equal(prepared, 1); assert.equal(restored, 1);
  } finally { if (previous === undefined) Reflect.deleteProperty(globalThis, "requestAnimationFrame"); else globalThis.requestAnimationFrame = previous; }
});


test("capture rejects changed indicator output references even when the market series and virtual time are unchanged", async () => {
  const previous = globalThis.requestAnimationFrame;
  globalThis.requestAnimationFrame = callback => { queueMicrotask(() => callback(0)); return 1; };
  try {
    const source = { ready: true, seriesKey: "series", sourceVersion: 1, interval: "1m", chartType: "candles", contextKey: "same clock" };
    let prepared = 0;
    const surface = { prepareExport: async () => { prepared++; return null; }, getExportSnapshot: () => null };
    await assert.rejects(captureReplayNoteChart(surface, context(), () => ({ ...source, presentation: [[]] })));
    assert.equal(prepared, 0);
  } finally { if (previous === undefined) Reflect.deleteProperty(globalThis, "requestAnimationFrame"); else globalThis.requestAnimationFrame = previous; }
});
