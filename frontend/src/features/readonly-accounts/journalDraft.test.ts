import assert from "node:assert/strict";
import test from "node:test";
import { draftFromVersion, draftSignature, parseJournalDraft, reconcileJournalDraft } from "./journalDraft.js";
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
