export interface ReplayNoteContext {
  runId: string; trackId: string; dataEpoch: string;
  runRevision: number; sourceSequence: number; checkpointSequence: number; timelineSequence: number; virtualTimeMs: number;
  reviewId: string | null; reviewRevision: number | null; reviewNote: boolean;
}
export interface ReplayNote {
  id: string; runId: string; trackId: string; marketTimeMs: number; effectiveTimeMs: number;
  createdAtMs: number; updatedAtMs: number; revisionCount: number;
  timelineSequence: number;
  fields: Record<string, string>; body: string; reviewNote: boolean; revisions: readonly never[];
}
export interface ReplayNotesResponse {
  protocol: "replay.v3"; schema_version: "replay.notes.v1"; run_id: string; track_id: string;
  context: ReplayNoteContext; asOfMs: number; notes: ReplayNote[];
}
export interface ReplayNoteSave {
  id: string; fields: Record<string, string>; expectedRevision: number; context: ReplayNoteContext;
}
const fail = (): never => { throw new TypeError("Invalid replay annotation response"); };
const record = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value)) return fail();
  return value as Record<string, unknown>;
};
const integer = (value: unknown, max = 253_402_300_799_999): number =>
  typeof value === "number" && Number.isSafeInteger(value) && value >= 0 && value <= max ? value : fail();
const text = (value: unknown, max = 128): string =>
  typeof value === "string" && value.length > 0 && value.length <= max ? value : fail();
const boolean = (value: unknown): boolean => typeof value === "boolean" ? value : fail();
const exact = (value: unknown, keys: string[]) => {
  const source = record(value);
  if (Object.keys(source).length !== keys.length || keys.some(key => !(key in source))) fail();
  return source;
};
export function parseReplayNoteContext(value: unknown): ReplayNoteContext {
  const source = exact(value, ["runId", "trackId", "dataEpoch", "runRevision", "sourceSequence", "checkpointSequence",
    "virtualTimeMs", "reviewId", "reviewRevision", "reviewNote", "timelineSequence"]);
  const context = { runId: text(source.runId), trackId: text(source.trackId), dataEpoch: text(source.dataEpoch),
    runRevision: integer(source.runRevision), sourceSequence: integer(source.sourceSequence),
    checkpointSequence: integer(source.checkpointSequence), virtualTimeMs: integer(source.virtualTimeMs),
    timelineSequence: integer(source.timelineSequence),
    reviewId: source.reviewId === null ? null : text(source.reviewId),
    reviewRevision: source.reviewRevision === null ? null : integer(source.reviewRevision), reviewNote: boolean(source.reviewNote) };
  if ((context.reviewId === null) !== (context.reviewRevision === null)
    || (context.reviewRevision !== null && (context.reviewRevision < 1 || !context.reviewNote))) fail();
  return context;
}
export function parseReplayNote(value: unknown): ReplayNote {
  const source = exact(value, ["id", "runId", "trackId", "marketTimeMs", "effectiveTimeMs", "createdAtMs",
    "updatedAtMs", "revisionCount", "fields", "body", "reviewNote", "revisions", "timelineSequence"]);
  const fields = record(source.fields);
  if (Object.keys(fields).length > 80 || Object.entries(fields).some(([key, value]) =>
    !key || key.length > 128 || typeof value !== "string")
    || new TextEncoder().encode(JSON.stringify(fields)).length > 65_536
    || source.body !== "" || !Array.isArray(source.revisions) || source.revisions.length !== 0) fail();
  const note = { id: text(source.id), runId: text(source.runId), trackId: text(source.trackId),
    marketTimeMs: integer(source.marketTimeMs), effectiveTimeMs: integer(source.effectiveTimeMs),
    createdAtMs: integer(source.createdAtMs), updatedAtMs: integer(source.updatedAtMs),
    revisionCount: integer(source.revisionCount, 100), fields: fields as Record<string, string>,
    body: "", reviewNote: boolean(source.reviewNote), revisions: [] };
  const timelineSequence = integer(source.timelineSequence);
  if (note.revisionCount < 1 || note.marketTimeMs > note.effectiveTimeMs) fail();
  return { ...note, timelineSequence };
}
export function parseReplayNotesResponse(value: unknown): ReplayNotesResponse {
  const source = exact(value, ["protocol", "schema_version", "run_id", "track_id", "context", "asOfMs", "notes"]);
  if (source.protocol !== "replay.v3" || source.schema_version !== "replay.notes.v1"
    || !Array.isArray(source.notes) || source.notes.length > 500) fail();
  const run_id = text(source.run_id), track_id = text(source.track_id), context = parseReplayNoteContext(source.context);
  const asOfMs = integer(source.asOfMs), notes = (source.notes as unknown[]).map(parseReplayNote);
  if (context.runId !== run_id || context.trackId !== track_id || asOfMs > context.virtualTimeMs
    || new Set(notes.map(note => note.id)).size !== notes.length
    || notes.some(note => note.runId !== run_id || note.trackId !== track_id || note.effectiveTimeMs > asOfMs || note.timelineSequence > context.timelineSequence)
    || new TextEncoder().encode(JSON.stringify(notes.map(note => note.fields))).length > 8 * 1024 * 1024) fail();
  return { protocol: "replay.v3", schema_version: "replay.notes.v1", run_id, track_id, context, asOfMs, notes };
}


export function sameReplayNoteContext(a: ReplayNoteContext, b: ReplayNoteContext): boolean {
  return Object.keys(a).length === Object.keys(b).length
    && (Object.keys(a) as (keyof ReplayNoteContext)[]).every(key => a[key] === b[key]);
}
export interface ReplayNoteVersionsResponse {
  protocol: "replay.v3"; schema_version: "replay.note-versions.v1";
  run_id: string; track_id: string; note_id: string; context: ReplayNoteContext;
  asOfMs: number; versions: ReplayNote[]; nextBeforeRevision: number | null;
}
export function parseReplayNoteVersions(value: unknown): ReplayNoteVersionsResponse {
  const source = exact(value, ["protocol", "schema_version", "run_id", "track_id", "note_id", "context", "asOfMs", "versions", "nextBeforeRevision"]);
  if (source.protocol !== "replay.v3" || source.schema_version !== "replay.note-versions.v1"
    || !Array.isArray(source.versions) || source.versions.length > 20) fail();
  const run_id = text(source.run_id), track_id = text(source.track_id), note_id = text(source.note_id);
  const context = parseReplayNoteContext(source.context), asOfMs = integer(source.asOfMs);
  const versions = (source.versions as unknown[]).map(parseReplayNote);
  const nextBeforeRevision = source.nextBeforeRevision === null ? null : integer(source.nextBeforeRevision, 100);
  if (context.runId !== run_id || context.trackId !== track_id || asOfMs > context.virtualTimeMs
    || versions.some((version, index) => version.id !== note_id || version.runId !== run_id || version.trackId !== track_id
      || version.effectiveTimeMs > asOfMs || version.timelineSequence > context.timelineSequence
      || (index > 0 && version.revisionCount >= versions[index - 1]!.revisionCount))
    || (nextBeforeRevision !== null && (nextBeforeRevision < 2 || nextBeforeRevision !== versions.at(-1)?.revisionCount))) fail();
  return { protocol: "replay.v3", schema_version: "replay.note-versions.v1", run_id, track_id, note_id,
    context, asOfMs, versions, nextBeforeRevision };
}
