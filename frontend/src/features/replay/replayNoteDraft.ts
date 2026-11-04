import { JournalDraftError, journalClientId } from "../trading-accounts/journalEditor.js";
import { parseReplayNoteContext, type ReplayNote, type ReplayNoteContext } from "./replayNotes.js";

type Store = Pick<Storage, "getItem" | "setItem" | "removeItem" | "key" | "length">;
interface Envelope {
  version: 1; context: ReplayNoteContext; noteId: string | null; noteRevision: number; draft: string;
}
export interface ReplayNoteDraft {
  key: string; context: ReplayNoteContext; noteId: string | null; noteRevision: number;
}
const prefix = (context: ReplayNoteContext) => "candlescope.replay-note-draft.v1:"
  + [context.runId, context.trackId, context.dataEpoch].map(encodeURIComponent).join(":") + ":";
const same = (a: ReplayNoteContext, b: ReplayNoteContext) =>
  Object.keys(a).length === Object.keys(b).length
    && (Object.keys(a) as (keyof ReplayNoteContext)[]).every(key => a[key] === b[key]);
function decode(raw: string): Envelope {
  const value = JSON.parse(raw) as Envelope;
  const context = parseReplayNoteContext(value.context);
  if (value.version !== 1 || typeof value.draft !== "string"
    || !(value.noteId === null || typeof value.noteId === "string")
    || !Number.isInteger(value.noteRevision) || value.noteRevision < 0 || value.noteRevision > 100)
    throw new JournalDraftError("storage");
  return { ...value, context };
}
function owned(envelope: Envelope, context: ReplayNoteContext) {
  return envelope.context.runId === context.runId && envelope.context.trackId === context.trackId
    && envelope.context.dataEpoch === context.dataEpoch;
}

/** Each temporal draft wraps the existing journal draft, retaining its original
 * save context across restart. A past view never opens a later draft's text. */
export function replayNoteDraftBinding(storage: Store, current: ReplayNoteContext, cutoff: number,
  note: ReplayNote | null, recovered?: ReplayNoteDraft) {
  const key = recovered?.key ?? prefix(current) + [note?.id ?? "new", note?.revisionCount ?? 0, cutoff,
    current.timelineSequence, current.runRevision, current.reviewId ?? "", current.reviewRevision ?? 0].join(":");
  const raw = storage.getItem(key);
  const initial = raw === null ? null : decode(raw);
  if (!key.startsWith(prefix(current)) || (initial && (!owned(initial, current) || initial.context.virtualTimeMs > cutoff
    || initial.context.timelineSequence > current.timelineSequence)))
    throw new JournalDraftError("changed");
  if (!initial && current.virtualTimeMs !== cutoff) throw new JournalDraftError("changed");
  const context = initial?.context ?? current;
  const noteId = initial?.noteId ?? note?.id ?? null;
  const noteRevision = initial?.noteRevision ?? note?.revisionCount ?? 0;
  const check = () => {
    const value = storage.getItem(key);
    if (value === null) return null;
    const envelope = decode(value);
    if (!owned(envelope, context) || !same(envelope.context, context)) throw new JournalDraftError("changed");
    return envelope;
  };
  return { key, context, noteId, noteRevision, storage: {
    getItem: () => check()?.draft ?? null,
    setItem: (_key: string, draft: string) => {
      check();
      storage.setItem(key, JSON.stringify({ version: 1, context, noteId, noteRevision, draft } satisfies Envelope));
    },
    removeItem: () => { check(); storage.removeItem(key); },
  } };
}

export function visibleReplayNoteDrafts(storage: Store, context: ReplayNoteContext, cutoff: number): ReplayNoteDraft[] {
  const drafts = [];
  for (let index = 0; index < storage.length; index++) {
    const key = storage.key(index);
    if (!key?.startsWith(prefix(context))) continue;
    const raw = storage.getItem(key);
    if (raw === null) continue;
    const envelope = decode(raw);
    if (owned(envelope, context) && envelope.context.virtualTimeMs <= cutoff
      && envelope.context.timelineSequence <= context.timelineSequence)
      drafts.push({ key, context: envelope.context, noteId: envelope.noteId, noteRevision: envelope.noteRevision });
  }
  return drafts;
}

/** Explicit copy only: retain the original pending submission and its retry ID. */
export function replayNoteCopyBinding(storage: Store, current: ReplayNoteContext, cutoff: number,
  source: ReturnType<typeof replayNoteDraftBinding>) {
  if (source.context.runId !== current.runId || source.context.trackId !== current.trackId
    || source.context.dataEpoch !== current.dataEpoch || source.context.virtualTimeMs > cutoff
    || source.context.timelineSequence > current.timelineSequence || current.virtualTimeMs !== cutoff)
    throw new JournalDraftError("changed");
  return replayNoteDraftBinding(storage, current, cutoff, null, {
    key: prefix(current) + "copy:" + journalClientId(), context: current, noteId: null, noteRevision: 0,
  });
}
