import assert from "node:assert/strict";
import test from "node:test";
import { JournalEditor } from "../../trading-accounts/journalEditor.js";
import { replayNoteCopyBinding, replayNoteDraftBinding, visibleReplayNoteDrafts } from "../replayNoteDraft.js";
import { parseReplayNotesResponse, parseReplayNoteVersions, type ReplayNote, type ReplayNoteContext } from "../replayNotes.js";
import { ReplayV2ApiClient } from "../replayV2Api.js";
import { ReplayDataManager } from "../replayDataManager.js";
import { managedReplayRunApi } from "../managedReplayTransport.js";

const context = (time = 100): ReplayNoteContext => ({ runId: "run", trackId: "track", dataEpoch: "epoch",
  runRevision: 1, sourceSequence: 1, checkpointSequence: 0, timelineSequence: 1, virtualTimeMs: time,
  reviewId: null, reviewRevision: null, reviewNote: false });
const note = (time = 100): ReplayNote => ({ id: "note", runId: "run", trackId: "track", marketTimeMs: time,
  effectiveTimeMs: time, createdAtMs: 1000, updatedAtMs: 1000, revisionCount: 1,
  fields: { entryBasis: "plan" }, body: "", reviewNote: false, revisions: [], timelineSequence: 1 });
const response = () => ({ protocol: "replay.v3", schema_version: "replay.notes.v1", run_id: "run", track_id: "track",
  context: context(), asOfMs: 100, notes: [note()] });
class Storage {
  values = new Map<string, string>();
  get length() { return this.values.size; }
  key(index: number) { return [...this.values.keys()][index] ?? null; }
  getItem(key: string) { return this.values.get(key) ?? null; }
  setItem(key: string, value: string) { this.values.set(key, value); }
  removeItem(key: string) { this.values.delete(key); }
}

test("note parser rejects future revisions, cross-run content and inconsistent review context", () => {
  assert.equal(parseReplayNotesResponse(response()).notes[0]!.fields.entryBasis, "plan");
  assert.throws(() => parseReplayNotesResponse({ ...response(), notes: [note(101)] }));
  assert.throws(() => parseReplayNotesResponse({ ...response(), notes: [{ ...note(), runId: "other" }] }));
  assert.throws(() => parseReplayNotesResponse({ ...response(), context: { ...context(), reviewId: "review" } }));
  assert.throws(() => parseReplayNotesResponse({ ...response(), notes: [note(), note()] }));
  assert.throws(() => parseReplayNotesResponse({ ...response(), notes: [{ ...note(), timelineSequence: 2 }] }));
});

test("uncertain save survives editor restart with original context and pending client identity", async () => {
  const storage = new Storage();
  const binding = replayNoteDraftBinding(storage, context(), 100, null);
  let submission: { id: string; fields: Record<string, string>; context: ReplayNoteContext } | null = null;
  const first = new JournalEditor<ReplayNote>({ key: binding.key, storage: () => binding.storage,
    create: async (fields, id) => { submission = { id, fields, context: binding.context }; throw new Error("response lost"); },
    save: async () => { throw new Error("not an edit"); }, quick: async () => undefined });
  first.initialize(null); first.edit({ entryBasis: "saved before restart" });
  assert.equal(await first.flush(), false); first.dispose();
  const visible = visibleReplayNoteDrafts(storage, { ...context(), runRevision: 9 }, 100);
  assert.equal(visible.length, 1);
  const recovered = replayNoteDraftBinding(storage, { ...context(), runRevision: 9 }, 100, null, visible[0]);
  assert.deepEqual(recovered.context, context());
  const second = new JournalEditor<ReplayNote>({ key: recovered.key, storage: () => recovered.storage,
    create: async (fields, id) => {
      assert.deepEqual({ id, fields, context: recovered.context }, submission);
      return { ...note(), id, fields };
    }, save: async () => { throw new Error("not an edit"); }, quick: async () => undefined });
  second.initialize(null);
  assert.equal(second.getSnapshot().recovered, true);
  assert.equal(await second.flush(), true);
  assert.equal(storage.length, 0); second.dispose();
});

test("backward views cannot discover or open future draft text and preserve stored recovery", () => {
  const storage = new Storage();
  const binding = replayNoteDraftBinding(storage, context(200), 200, null);
  binding.storage.setItem(binding.key, JSON.stringify({ fields: { entryBasis: "future draft" } }));
  const saved = storage.getItem(binding.key);
  assert.deepEqual(visibleReplayNoteDrafts(storage, context(100), 100), []);
  assert.throws(() => replayNoteDraftBinding(storage, context(100), 100, null,
    { key: binding.key, context: context(200), noteId: null, noteRevision: 0 }));
  assert.equal(storage.getItem(binding.key), saved);
  assert.throws(() => replayNoteDraftBinding(storage, context(200), 100, null));
});

test("same-millisecond drafts from later events stay hidden at an earlier event", () => {
  const storage = new Storage();
  const later = { ...context(), timelineSequence: 2 };
  const binding = replayNoteDraftBinding(storage, later, 100, null);
  binding.storage.setItem(binding.key, JSON.stringify({ fields: { entryBasis: "later event draft" } }));
  const earlier = replayNoteDraftBinding(storage, context(), 100, null);
  assert.notEqual(earlier.key, binding.key);
  assert.equal(earlier.storage.getItem(earlier.key), null);
  assert.deepEqual(visibleReplayNoteDrafts(storage, context(), 100), []);
  assert.throws(() => replayNoteDraftBinding(storage, context(), 100, null,
    { key: binding.key, context: later, noteId: null, noteRevision: 0 }));
});

test("notes parsed body remains inside the manager lease and closed view cannot receive late text", async () => {
  const manager = new ReplayDataManager();
  const lease = manager.createOperations({ runId: "run", purpose: "review" });
  const release = lease.retain();
  let complete!: (value: string) => void;
  const api = new ReplayV2ApiClient({ fetcher: async () => {
    const value = new Response(); value.text = () => new Promise(resolve => { complete = resolve; }); return value;
  } });
  const pending = managedReplayRunApi(lease, api).notesRun("run", "track", 100);
  await Promise.resolve();
  assert.equal(manager.diagnostics().requests, 1);
  const rejected = assert.rejects(pending, { name: "AbortError" });
  release(); await rejected; complete(JSON.stringify(response()));
  assert.equal(manager.diagnostics().requests, 0); manager.dispose();
});


test("explicit current-time copies retain the original pending draft and cannot backdate future text", async () => {
  const storage = new Storage();
  const source = replayNoteDraftBinding(storage, context(), 100, null);
  const editor = new JournalEditor<ReplayNote>({ key: source.key, storage: () => source.storage,
    create: async () => { throw new Error("uncertain reply"); },
    save: async () => { throw new Error("unexpected edit"); }, quick: async () => undefined });
  editor.initialize(null); editor.edit({ entryBasis: "original pending text" });
  assert.equal(await editor.flush(), false); editor.dispose();
  const original = storage.getItem(source.key);
  const current = { ...context(200), runRevision: 2, timelineSequence: 2, reviewId: "review", reviewRevision: 1, reviewNote: true };
  const copy = replayNoteCopyBinding(storage, current, 200, source);
  const copied = new JournalEditor<ReplayNote>({ key: copy.key, storage: () => copy.storage,
    create: async (fields, id) => ({ ...note(200), id, fields, reviewNote: true }),
    save: async () => { throw new Error("unexpected edit"); }, quick: async () => undefined });
  copied.initialize(null, { entryBasis: "original pending text" }); copied.edit(copied.getSnapshot().fields);
  assert.notEqual(copy.key, source.key); assert.deepEqual(copy.context, current);
  assert.equal(await copied.flush(), true); copied.dispose();
  assert.equal(storage.getItem(source.key), original);
  assert.throws(() => replayNoteCopyBinding(storage, context(50), 50, source));
  assert.throws(() => replayNoteCopyBinding(storage, { ...current, dataEpoch: "other" }, 200, source));
});

const versionsResponse = () => ({ protocol: "replay.v3", schema_version: "replay.note-versions.v1",
  run_id: "run", track_id: "track", note_id: "note", context: context(), asOfMs: 100,
  versions: [{ ...note(), revisionCount: 3 }, { ...note(), revisionCount: 2 }], nextBeforeRevision: 2 });

test("version pages reject future text, duplicate/out-of-order versions and invalid continuation", () => {
  assert.equal(parseReplayNoteVersions(versionsResponse()).nextBeforeRevision, 2);
  for (const invalid of [
    { versions: [{ ...note(), effectiveTimeMs: 101 }] },
    { versions: [{ ...note(), timelineSequence: 2 }] },
    { versions: [{ ...note(), runId: "other" }] },
    { versions: [note(), note()] },
    { versions: [note(), { ...note(), revisionCount: 2 }] },
    { nextBeforeRevision: 3 }, { versions: [], nextBeforeRevision: 2 },
  ]) assert.throws(() => parseReplayNoteVersions({ ...versionsResponse(), ...invalid }));
});

test("version pages honor request cursor/size and late parsed history cannot outlive the manager lease", async () => {
  const manager = new ReplayDataManager();
  const lease = manager.createOperations({ runId: "run", purpose: "review" });
  const release = lease.retain();
  let complete!: (value: string) => void;
  const api = new ReplayV2ApiClient({ fetcher: async (url) => {
    assert.match(String(url), /notes\/note\/versions\?at_time_ms=100&limit=20&before_revision=4$/);
    const value = new Response(); value.text = () => new Promise(resolve => { complete = resolve; }); return value;
  } });
  const pending = managedReplayRunApi(lease, api).noteVersionsRun("run", "track", "note", { atTimeMs: 100, beforeRevision: 4 });
  await Promise.resolve();
  assert.equal(manager.diagnostics().requests, 1);
  const rejected = assert.rejects(pending, { name: "AbortError" });
  release(); await rejected; complete(JSON.stringify(versionsResponse())); manager.dispose();
  assert.equal(manager.diagnostics().requests, 0);
  const invalidApi = new ReplayV2ApiClient({ fetcher: async () => Response.json(versionsResponse()) });
  await assert.rejects(invalidApi.noteVersionsRun("run", "track", "note", { atTimeMs: 100, beforeRevision: 3 }));
  await assert.rejects(invalidApi.noteVersionsRun("run", "track", "note", { atTimeMs: 100, limit: 1 }));
});
