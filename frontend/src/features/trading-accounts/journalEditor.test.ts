import assert from "node:assert/strict";
import test from "node:test";
import { JournalDraftError, JournalEditor, type JournalDraft } from "./journalEditor.js";
import type { JournalEntry } from "./tradingTypes.js";

const entry = (fields: Record<string, string>, revisionCount = 1) => ({
  id: "je_00000000000000000001", fields, revisionCount,
}) as JournalEntry;
function fixture() {
  const values = new Map<string, string>();
  const storage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
    removeItem: (key: string) => { values.delete(key); },
  };
  let id = 0;
  const options = {
    key: "account:a:trade:t", storage: () => storage, newId: () => String(++id),
    create: async (fields: Record<string, string>) => entry(fields),
    save: async (_id: string, fields: Record<string, string>, revision: number) => entry(fields, revision + 1),
    quick: async () => {},
  };
  return { values, storage, options };
}

test("failed close preserves draft across a new editor and keeps the base revision", async () => {
  const f = fixture();
  const editor = new JournalEditor({ ...f.options, save: async () => { throw new Error("offline"); } });
  editor.initialize(entry({ entryBasis: "old" }, 3));
  editor.edit({ entryBasis: "new" });
  assert.equal(await editor.flush(), false);
  assert.equal(editor.getSnapshot().status, "failed");
  editor.dispose();
  let expected = 0;
  const restarted = new JournalEditor({ ...f.options, save: async (_id, fields, revision) => {
    expected = revision;
    return entry(fields, revision + 1);
  } });
  restarted.initialize(entry({ entryBasis: "old" }, 3));
  assert.equal(restarted.getSnapshot().fields.entryBasis, "new");
  assert.equal(restarted.getSnapshot().recovered, true);
  assert.equal(await restarted.flush(), true);
  assert.equal(expected, 3);
  assert.equal(f.values.size, 0);
});

test("edits during a save are serialized and close waits for the latest content", async () => {
  const f = fixture();
  let release!: (value: JournalEntry) => void;
  const writes: { fields: Record<string, string>; revision: number }[] = [];
  const editor = new JournalEditor({ ...f.options, save: async (_id, fields, revision) => {
    writes.push({ fields, revision });
    if (writes.length === 1) return new Promise<JournalEntry>((resolve) => { release = resolve; });
    return entry(fields, revision + 1);
  } });
  editor.initialize(entry({ entryBasis: "original" }));
  editor.edit({ entryBasis: "first" });
  const saving = editor.flush();
  editor.edit({ entryBasis: "second" });
  const closing = editor.flush();
  assert.equal(writes.length, 1);
  assert.equal(saving, closing);
  release(entry({ entryBasis: "first" }, 2));
  assert.equal(await closing, true);
  assert.deepEqual(writes, [
    { fields: { entryBasis: "first" }, revision: 1 },
    { fields: { entryBasis: "second" }, revision: 2 },
  ]);
  assert.equal(editor.getSnapshot().fields.entryBasis, "second");
  assert.equal(f.values.size, 0);
});

test("late completion after unmount does not erase a reopened draft", async () => {
  const f = fixture();
  let release!: (value: JournalEntry) => void;
  const old = new JournalEditor({ ...f.options, save: () => new Promise((resolve) => { release = resolve; }) });
  old.initialize(entry({ entryBasis: "old" }));
  old.edit({ entryBasis: "sent" });
  const saving = old.flush();
  old.dispose();
  const reopened = new JournalEditor(f.options);
  reopened.initialize(entry({ entryBasis: "old" }));
  reopened.edit({ entryBasis: "reopened" });
  release(entry({ entryBasis: "sent" }, 2));
  assert.equal(await saving, false);
  assert.equal((JSON.parse(f.values.get(f.options.key)!) as JournalDraft).fields.entryBasis, "reopened");
});

test("creation retry after restart reuses the persisted identifier", async () => {
  const f = fixture();
  const ids: string[] = [];
  const first = new JournalEditor({ ...f.options, create: async (_fields, id) => {
    ids.push(id); throw new Error("response lost");
  } });
  first.initialize(null);
  first.edit({ entryBasis: "new note" });
  assert.equal(await first.flush(), false);
  first.dispose();
  const second = new JournalEditor({ ...f.options, create: async (fields, id) => { ids.push(id); return entry(fields); } });
  second.initialize(null);
  assert.equal(await second.flush(), true);
  assert.equal(ids[0], ids[1]);
});

test("quick text survives template saves and account draft keys stay isolated", async () => {
  const f = fixture();
  const a = new JournalEditor(f.options);
  a.initialize(entry({ entryBasis: "a" }));
  a.editQuick("unsent quick note");
  a.edit({ entryBasis: "changed" });
  assert.equal(await a.flush(), true);
  const b = new JournalEditor({ ...f.options, key: "account:b:trade:t" });
  b.initialize(null);
  assert.equal(b.getSnapshot().quickText, "");
  const reopened = new JournalEditor(f.options);
  reopened.initialize(entry({ entryBasis: "changed" }, 2));
  assert.equal(reopened.getSnapshot().quickText, "unsent quick note");
  assert.equal(await reopened.saveQuick(), true);
  assert.equal(f.values.size, 0);
});

test("storage failures and competing drafts block close without discarding input", async () => {
  const f = fixture();
  const a = new JournalEditor(f.options);
  a.initialize(entry({}));
  a.edit({ entryBasis: "a" });
  const b = new JournalEditor(f.options);
  b.initialize(entry({}));
  b.edit({ entryBasis: "b" });
  assert.equal(await a.flush(), false);
  assert.ok(a.getSnapshot().error instanceof JournalDraftError);
  assert.equal(a.getSnapshot().fields.entryBasis, "a");
  assert.equal((JSON.parse(f.values.get(f.options.key)!) as JournalDraft).fields.entryBasis, "b");
  f.storage.setItem = () => { throw new Error("quota"); };
  b.edit({ entryBasis: "still here" });
  assert.equal(await b.flush(), false);
  assert.equal(b.getSnapshot().fields.entryBasis, "still here");
});

test("quick note retry preserves edits made after a lost response", async () => {
  const f = fixture();
  const writes: { text: string; id: string }[] = [];
  let offline = true;
  const options = { ...f.options, quick: async (text: string, id: string) => {
    writes.push({ text, id });
    if (offline) throw new Error("lost response");
  } };
  const editor = new JournalEditor(options);
  editor.initialize(entry({}));
  editor.editQuick("first");
  assert.equal(await editor.saveQuick(), false);
  editor.editQuick("second");
  editor.dispose();
  offline = false;
  const reopened = new JournalEditor(options);
  reopened.initialize(entry({}));
  assert.equal(await reopened.saveQuick(), true);
  assert.equal(reopened.getSnapshot().quickText, "second");
  assert.deepEqual(writes[0], writes[1]);
  assert.equal(await reopened.saveQuick(), true);
  assert.equal(writes[2]!.text, "second");
  assert.notEqual(writes[2]!.id, writes[0]!.id);
});

test("blank fields removed by the server do not trigger an endless save loop", async () => {
  const f = fixture();
  let writes = 0;
  const editor = new JournalEditor({ ...f.options, save: async () => {
    writes++;
    return entry({ entryBasis: "new" }, 2);
  } });
  editor.initialize(entry({ entryBasis: "old" }));
  editor.edit({ entryBasis: "new", marketEnv: "   " });
  assert.equal(await editor.flush(), true);
  assert.equal(writes, 1);
});

test("a revert during an uncertain save survives restart and follows the pending write", async () => {
  const f = fixture();
  const first = new JournalEditor({ ...f.options, save: async () => { throw new Error("response lost"); } });
  first.initialize(entry({ entryBasis: "original" }));
  first.edit({ entryBasis: "in flight" });
  const saving = first.flush();
  first.edit({ entryBasis: "original" });
  assert.equal(await saving, false);
  first.dispose();
  const writes: string[] = [];
  const restarted = new JournalEditor({ ...f.options, save: async (_id, fields, revision) => {
    writes.push(fields.entryBasis!);
    return entry(fields, revision + 1);
  } });
  restarted.initialize(entry({ entryBasis: "original" }));
  assert.equal(await restarted.flush(), true);
  assert.deepEqual(writes, ["in flight", "original"]);
  assert.equal(restarted.getSnapshot().fields.entryBasis, "original");
  assert.equal(f.values.size, 0);
});
