import assert from "node:assert/strict";
import test from "node:test";
import { draftFromVersion, draftSignature, newJournalDraft, parseJournalDraft, reconcileJournalDraft, startLinkedJournalDraft } from "./journalDraft.js";
import type { JournalVersion } from "./accountApi.js";

const first: JournalVersion = { noteId: "a".repeat(32), version: 1, eventMs: 10, recordedMs: 20, fillId: null,
  payload: { kind: "plan", text: "original plan", tags: ["one", "two"] } };
const second: JournalVersion = { ...first, version: 2, recordedMs: 30, payload: { ...first.payload, text: "first revision" } };

test("restart recovers a committed autosave without overwriting text typed during the request", () => {
  const sent = { ...draftFromVersion(first), text: second.payload.text, tags: "one，two" };
  const pending = { ...sent, text: "newer local thought", pending: { baseVersion: 1, signature: draftSignature(sent) } };
  const restarted = parseJournalDraft(JSON.stringify(pending));
  const recovered = reconcileJournalDraft(restarted, [second, first]);
  assert.equal(recovered.baseVersion, 2);
  assert.equal(recovered.text, "newer local thought");
  assert.equal(recovered.eventMs, 10);
  assert.equal(recovered.savedSignature, draftSignature(draftFromVersion(second)));
  assert.notEqual(recovered.savedSignature, draftSignature(recovered));
  assert.equal(recovered.pending, undefined);
});

test("an unrelated concurrent revision cannot silently rebase or replace a local draft", () => {
  const draft = { ...draftFromVersion(first), text: "unsaved plan", pending: { baseVersion: 1, signature: "a different request" } };
  assert.equal(reconcileJournalDraft(draft, [second]), draft);
});

test("saved entries recover consistently and corrupt timestamps cannot break the journal", () => {
  const draft = draftFromVersion(first);
  assert.deepEqual(parseJournalDraft(JSON.stringify(draft)), draft);
  assert.equal(reconcileJournalDraft(draft, [first]).savedSignature, draftSignature(draft));
  for (const eventMs of [-1, 1e20, Infinity]) {
    const restored = parseJournalDraft(JSON.stringify({ ...draft, eventMs }));
    assert.notEqual(restored.noteId, draft.noteId);
    assert.ok(Number.isFinite(new Date(restored.eventMs).getTime()));
  }
});

test("adding a fill note creates an independent identity and never reassigns a saved note", () => {
  const original = { ...first, fillId: "fill-one" };
  const draft = draftFromVersion(original);
  const before = structuredClone(draft);
  for (const fillId of ["fill-one", "fill-two"]) {
    const next = startLinkedJournalDraft(draft, fillId)!;
    assert.notEqual(next.noteId, draft.noteId);
    assert.equal(next.fillId, fillId);
    assert.equal(next.baseVersion, 0);
    assert.equal(next.text, "");
    assert.equal(next.tags, "");
    assert.equal(next.kind, "note");
    assert.deepEqual(draft, before);
  }
});

test("switching fills retains unsaved edits, empty edited records and pending saves", () => {
  const saved = draftFromVersion({ ...first, fillId: "fill-one" });
  const blank = newJournalDraft();
  for (const draft of [
    { ...saved, text: "new unsaved observation" }, { ...saved, text: "" },
    { ...blank, tags: "unsaved tag" }, { ...blank, kind: "plan" as const },
    { ...saved, pending: { baseVersion: 1, signature: draftSignature(saved) } },
  ]) {
    const before = structuredClone(draft);
    assert.equal(startLinkedJournalDraft(draft, "fill-two"), null);
    assert.deepEqual(draft, before);
  }
  assert.equal(startLinkedJournalDraft(blank, "fill-two")?.fillId, "fill-two");
});

test("a lost save response is reconciled before starting a note for another fill", () => {
  const draft = { ...draftFromVersion({ ...first, fillId: "fill-one" }), text: "saved while leaving the panel" };
  const pending = { ...draft, pending: { baseVersion: 1, signature: draftSignature(draft) } };
  assert.equal(startLinkedJournalDraft(pending, "fill-two"), null);
  const committed = { ...first, fillId: "fill-one", version: 2, payload: { ...first.payload, text: draft.text } };
  const recovered = reconcileJournalDraft(parseJournalDraft(JSON.stringify(pending)), [committed, first]);
  assert.equal(recovered.fillId, "fill-one");
  assert.equal(recovered.baseVersion, 2);
  const next = startLinkedJournalDraft(recovered, "fill-two")!;
  assert.notEqual(next.noteId, recovered.noteId);
  assert.equal(next.fillId, "fill-two");
  assert.equal(committed.fillId, "fill-one");
});
