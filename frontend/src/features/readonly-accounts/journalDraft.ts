import { record, type JournalVersion } from "./accountApi.js";

export const JOURNAL_DRAFT_KEY = "candlescope.readonly-account.journal-draft.v1";
export interface LinkedNoteRequest { id: string; fillId: string }
export interface JournalDraft {
  noteId: string;
  baseVersion: number;
  text: string;
  tags: string;
  kind: JournalVersion["payload"]["kind"];
  eventMs: number;
  fillId?: string;
  savedSignature: string;
  pending?: { baseVersion: number; signature: string };
}
export function draftTags(tags: string): string[] {
  return tags.split(/[,，]/).map((tag) => tag.trim()).filter(Boolean);
}
export function draftSignature(draft: JournalDraft): string {
  return JSON.stringify([draft.noteId, draft.text, draftTags(draft.tags), draft.kind, draft.eventMs, draft.fillId]);
}
export function newJournalDraft(fillId?: string): JournalDraft {
  return { noteId: crypto.randomUUID().replaceAll("-", ""), baseVersion: 0, text: "", tags: "", kind: "note", eventMs: Date.now(), savedSignature: "", ...(fillId ? { fillId } : {}) };
}
/** Adding a fill note never changes the identity or association of an existing note. */
export function startLinkedJournalDraft(draft: JournalDraft, fillId: string): JournalDraft | null {
  const saved = draftSignature(draft) === draft.savedSignature;
  const hasChanges = draft.baseVersion > 0 || Boolean(draft.text.trim() || draft.tags.trim()) || draft.kind !== "note";
  if (draft.pending || (!saved && hasChanges)) return null;
  return newJournalDraft(fillId);
}
export function draftFromVersion(row: JournalVersion): JournalDraft {
  const draft: JournalDraft = { noteId: row.noteId, baseVersion: row.version, text: row.payload.text,
    tags: row.payload.tags.join(", "), kind: row.payload.kind, eventMs: row.eventMs,
    ...(row.fillId ? { fillId: row.fillId } : {}), savedSignature: "" };
  draft.savedSignature = draftSignature(draft);
  return draft;
}
export function parseJournalDraft(raw: string | null): JournalDraft {
  try {
    const value: unknown = JSON.parse(raw ?? "null");
    if (record(value) && typeof value.noteId === "string" && /^[a-f0-9]{32}$/.test(value.noteId)
      && typeof value.baseVersion === "number" && Number.isSafeInteger(value.baseVersion) && value.baseVersion >= 0
      && typeof value.text === "string" && value.text.length <= 8000 && typeof value.tags === "string" && value.tags.length <= 800
      && typeof value.savedSignature === "string" && ["plan", "note", "review"].includes(String(value.kind))
      && typeof value.eventMs === "number" && Number.isSafeInteger(value.eventMs) && value.eventMs >= 0 && value.eventMs < 8_640_000_000_000_000 - 86_400_000
      && (value.fillId === undefined || typeof value.fillId === "string")
      && (value.pending === undefined || (record(value.pending) && typeof value.pending.baseVersion === "number"
        && Number.isSafeInteger(value.pending.baseVersion) && value.pending.baseVersion >= 0 && typeof value.pending.signature === "string"))) return value as unknown as JournalDraft;
  } catch { /* Invalid local drafts never prevent reading the durable journal. */ }
  return newJournalDraft();
}
export function reconcileJournalDraft(draft: JournalDraft, rows: JournalVersion[]): JournalDraft {
  const latest = rows.filter((row) => row.noteId === draft.noteId).sort((a, b) => b.version - a.version)[0];
  if (!latest) return draft;
  const actual = draftSignature(draftFromVersion(latest));
  // Recover a committed save whose response was lost or arrived after unmount.
  // Preserve text entered while that save was pending; it becomes the next version.
  if (actual === draftSignature(draft) || (draft.pending && latest.version === draft.pending.baseVersion + 1 && actual === draft.pending.signature)) {
    const { pending: _pending, ...current } = draft;
    return { ...current, baseVersion: latest.version, savedSignature: actual };
  }
  return draft;
}
