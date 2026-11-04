export interface ReplayNoteContext {
  runId: string; trackId: string; dataEpoch: string;
  runRevision: number; sourceSequence: number; checkpointSequence: number; timelineSequence: number; virtualTimeMs: number;
  reviewId: string | null; reviewRevision: number | null; reviewNote: boolean;
}
export interface ReplayNoteLink {
  kind: "FILL" | "TRADE"; id: string; fillId: string; eventTimeMs: number; sourceSequence: number;
  side: "BUY" | "SELL"; quantity: string; price: string;
}
export interface ReplayNoteCapture {
  id: string; runId: string; trackId: string; dataEpoch: string; marketTimeMs: number; timelineSequence: number;
  savedAtMs: number; width: number; height: number; interval: string; chartType: string;
}
export interface ReplayNote {
  id: string; runId: string; trackId: string; marketTimeMs: number; effectiveTimeMs: number;
  createdAtMs: number; updatedAtMs: number; revisionCount: number;
  timelineSequence: number;
  links?: ReplayNoteLink[]; screenshots?: ReplayNoteCapture[];
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
    "updatedAtMs", "revisionCount", "fields", "body", "reviewNote", "revisions", "timelineSequence",
    ...("links" in record(value) ? ["links"] : []), ...("screenshots" in record(value) ? ["screenshots"] : [])]);
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
  const links = source.links === undefined ? [] : parseReplayNoteLinks(source.links, 8);
  if (links.some(link => link.eventTimeMs > note.effectiveTimeMs)) fail();
  const screenshots = source.screenshots === undefined ? [] : parseReplayNoteCaptures(source.screenshots, 2);
  if (source.screenshots !== undefined && JSON.stringify(replayNoteSelectedCaptures(note.fields)) !== JSON.stringify(screenshots.map(capture => capture.id))) fail();
  if (screenshots.some(capture => capture.runId !== note.runId || capture.trackId !== note.trackId
    || capture.marketTimeMs > note.effectiveTimeMs || capture.timelineSequence > timelineSequence)) fail();
  return { ...note, timelineSequence, ...(source.links === undefined ? {} : { links }),
    ...(source.screenshots === undefined ? {} : { screenshots }) };
}
export function parseReplayNotesResponse(value: unknown): ReplayNotesResponse {
  const source = exact(value, ["protocol", "schema_version", "run_id", "track_id", "context", "asOfMs", "notes"]);
  if (source.protocol !== "replay.v3" || source.schema_version !== "replay.notes.v1"
    || !Array.isArray(source.notes) || source.notes.length > 500) fail();
  const run_id = text(source.run_id), track_id = text(source.track_id), context = parseReplayNoteContext(source.context);
  const asOfMs = integer(source.asOfMs), notes = (source.notes as unknown[]).map(parseReplayNote);
  if (context.runId !== run_id || context.trackId !== track_id || asOfMs > context.virtualTimeMs
    || new Set(notes.map(note => note.id)).size !== notes.length
    || notes.some(note => note.runId !== run_id || note.trackId !== track_id || note.effectiveTimeMs > asOfMs || note.timelineSequence > context.timelineSequence
      || note.screenshots?.some(capture => capture.dataEpoch !== context.dataEpoch))
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
      || version.screenshots?.some(capture => capture.dataEpoch !== context.dataEpoch)
      || (index > 0 && version.revisionCount >= versions[index - 1]!.revisionCount))
    || (nextBeforeRevision !== null && (nextBeforeRevision < 2 || nextBeforeRevision !== versions.at(-1)?.revisionCount))) fail();
  return { protocol: "replay.v3", schema_version: "replay.note-versions.v1", run_id, track_id, note_id,
    context, asOfMs, versions, nextBeforeRevision };
}

export function parseReplayNoteLinks(value: unknown, maximum: number): ReplayNoteLink[] {
  if (!Array.isArray(value) || value.length > maximum) return fail();
  const links = value.map((item): ReplayNoteLink => {
    const source = exact(item, ["kind", "id", "fillId", "eventTimeMs", "sourceSequence", "side", "quantity", "price"]);
    if ((source.kind !== "FILL" && source.kind !== "TRADE") || (source.side !== "BUY" && source.side !== "SELL")) return fail();
    const quantity = text(source.quantity, 256), price = text(source.price, 256);
    if ([quantity, price].some(amount => !/^\d+(?:\.\d+)?$/.test(amount) || !/[1-9]/.test(amount))) return fail();
    return { kind: source.kind, id: text(source.id), fillId: text(source.fillId), eventTimeMs: integer(source.eventTimeMs),
      sourceSequence: integer(source.sourceSequence), side: source.side, quantity, price };
  });
  if (new Set(links.map(link => link.kind + ":" + link.id)).size !== links.length) return fail();
  return links;
}
export interface ReplayNoteLinkOptions {
  protocol: "replay.v3"; schema_version: "replay.note-links.v1"; context: ReplayNoteContext;
  kind: "FILL" | "TRADE"; links: ReplayNoteLink[]; nextBeforeId: string | null;
}
export function parseReplayNoteLinkOptions(value: unknown): ReplayNoteLinkOptions {
  const source = exact(value, ["protocol", "schema_version", "context", "kind", "links", "nextBeforeId"]);
  if (source.protocol !== "replay.v3" || source.schema_version !== "replay.note-links.v1"
    || (source.kind !== "FILL" && source.kind !== "TRADE")) return fail();
  const context = parseReplayNoteContext(source.context), links = parseReplayNoteLinks(source.links, 20);
  const nextBeforeId = source.nextBeforeId === null ? null : text(source.nextBeforeId);
  if (links.some((link, index) => link.kind !== source.kind || link.eventTimeMs > context.virtualTimeMs
    || (index > 0 && link.id >= links[index - 1]!.id))
    || (nextBeforeId !== null && nextBeforeId !== links.at(-1)?.id)) return fail();
  return { protocol: "replay.v3", schema_version: "replay.note-links.v1", context, kind: source.kind, links, nextBeforeId };
}
export const replayNoteLinkField = (kind: ReplayNoteLink["kind"]) => kind === "FILL" ? "replayFillIds" : "replayTradeIds";
function selectedIds(fields: Record<string, string>, field: string, maximum: number): string[] {
  const value: unknown = JSON.parse(fields[field] ?? "[]");
  if (!Array.isArray(value) || value.length > maximum || value.some(id => typeof id !== "string" || id.length < 1 || id.length > 128)
    || new Set(value).size !== value.length) return fail();
  return value as string[];
}
export const replayNoteSelectedCaptures = (fields: Record<string, string>): string[] => selectedIds(fields, "replayScreenshotIds", 2);
export const replayNoteSelectedLinks = (fields: Record<string, string>, kind: ReplayNoteLink["kind"]): string[] => selectedIds(fields, replayNoteLinkField(kind), 8);

export function parseReplayNoteCaptures(value: unknown, maximum = 128): ReplayNoteCapture[] {
  if (!Array.isArray(value) || value.length > maximum) return fail();
  const captures = value.map(item => {
    const source = exact(item, ["id", "runId", "trackId", "dataEpoch", "marketTimeMs", "timelineSequence", "savedAtMs", "width", "height", "interval", "chartType"]);
    const width = integer(source.width, 4096), height = integer(source.height, 4096);
    if (width < 1 || height < 1) return fail();
    return { id: text(source.id), runId: text(source.runId), trackId: text(source.trackId), dataEpoch: text(source.dataEpoch),
      marketTimeMs: integer(source.marketTimeMs), timelineSequence: integer(source.timelineSequence), savedAtMs: integer(source.savedAtMs),
      width, height, interval: text(source.interval, 32), chartType: text(source.chartType, 32) };
  });
  if (new Set(captures.map(capture => capture.id)).size !== captures.length) return fail();
  return captures;
}
export interface ReplayNoteCaptureSave {
  id: string; image: string; context: ReplayNoteContext; capturedContext: ReplayNoteContext;
  chart: { interval: string; chartType: string; seriesKey: string; sourceVersion: number };
}
export interface ReplayNoteCaptureReceipt {
  protocol: "replay.v3"; schema_version: "replay.note-capture.v1"; context: ReplayNoteContext; capture: ReplayNoteCapture;
}
const captureWithin = (capture: ReplayNoteCapture, context: ReplayNoteContext) => capture.runId === context.runId
  && capture.trackId === context.trackId && capture.dataEpoch === context.dataEpoch
  && capture.marketTimeMs <= context.virtualTimeMs && capture.timelineSequence <= context.timelineSequence;
export function parseReplayNoteCaptureReceipt(value: unknown): ReplayNoteCaptureReceipt {
  const source = exact(value, ["protocol", "schema_version", "context", "capture"]);
  if (source.protocol !== "replay.v3" || source.schema_version !== "replay.note-capture.v1") return fail();
  const context = parseReplayNoteContext(source.context), capture = parseReplayNoteCaptures([source.capture], 1)[0]!;
  if (!captureWithin(capture, context)) return fail();
  return { protocol: "replay.v3", schema_version: "replay.note-capture.v1", context, capture };
}
export interface ReplayNoteCapturesResponse {
  protocol: "replay.v3"; schema_version: "replay.note-captures.v1"; context: ReplayNoteContext; captures: ReplayNoteCapture[];
}
export function parseReplayNoteCapturesResponse(value: unknown): ReplayNoteCapturesResponse {
  const source = exact(value, ["protocol", "schema_version", "context", "captures"]);
  if (source.protocol !== "replay.v3" || source.schema_version !== "replay.note-captures.v1") return fail();
  const context = parseReplayNoteContext(source.context), captures = parseReplayNoteCaptures(source.captures);
  if (captures.some(capture => !captureWithin(capture, context))) return fail();
  return { protocol: "replay.v3", schema_version: "replay.note-captures.v1", context, captures };
}
export interface ReplayNoteImageResponse {
  protocol: "replay.v3"; schema_version: "replay.note-image.v1"; context: ReplayNoteContext;
  note_id: string; revision: number; capture: ReplayNoteCapture; image: string;
}
export function parseReplayNoteImageResponse(value: unknown): ReplayNoteImageResponse {
  const source = exact(value, ["protocol", "schema_version", "context", "note_id", "revision", "capture", "image"]);
  if (source.protocol !== "replay.v3" || source.schema_version !== "replay.note-image.v1") return fail();
  const context = parseReplayNoteContext(source.context), capture = parseReplayNoteCaptures([source.capture], 1)[0]!;
  const revision = integer(source.revision, 100);
  if (revision < 1 || !captureWithin(capture, context) || typeof source.image !== "string" || source.image.length > 2_796_226
    || !/^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/.test(source.image)) return fail();
  return { protocol: "replay.v3", schema_version: "replay.note-image.v1", context, note_id: text(source.note_id), revision, capture, image: source.image };
}
