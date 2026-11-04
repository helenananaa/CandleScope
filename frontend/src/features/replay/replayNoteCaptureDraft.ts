import { JournalDraftError, journalClientId } from "../trading-accounts/journalEditor.js";
import { replayNoteSelectedCaptures, parseReplayNoteContext, sameReplayNoteContext, type ReplayNoteCaptureSave, type ReplayNoteContext } from "./replayNotes.js";

type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;
export const replayNoteScreenshotField = "replayScreenshotIds";
export const replayNotePendingCaptureField = "replayPendingCaptureId";
const prefix = "candlescope.replay-note-capture-draft.v1:";
const fail = (): never => { throw new JournalDraftError("storage"); };
const owned = (a: ReplayNoteContext, b: ReplayNoteContext) => a.runId === b.runId && a.trackId === b.trackId && a.dataEpoch === b.dataEpoch;
const within = (a: ReplayNoteContext, b: ReplayNoteContext) => owned(a, b) && a.virtualTimeMs <= b.virtualTimeMs && a.timelineSequence <= b.timelineSequence;
const key = (id: string) => prefix + encodeURIComponent(id);

export const replayNoteScreenshotIds = replayNoteSelectedCaptures;
export function replayNotePendingCapture(fields: Record<string, string>): string | null {
  const value = fields[replayNotePendingCaptureField];
  if (value === undefined) return null;
  if (value.length < 1 || value.length > 128) return fail();
  return value;
}
function decode(raw: string): ReplayNoteCaptureSave {
  const value = JSON.parse(raw) as ReplayNoteCaptureSave;
  const context = parseReplayNoteContext(value.context), capturedContext = parseReplayNoteContext(value.capturedContext);
  const chart = value.chart;
  if (Object.keys(value).sort().join() !== ["capturedContext", "chart", "context", "id", "image"].sort().join()
    || typeof value.id !== "string" || value.id.length < 1 || value.id.length > 128
    || typeof value.image !== "string" || value.image.length > 2_796_226
    || !/^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/.test(value.image) || !within(capturedContext, context)
    || !chart || Object.keys(chart).sort().join() !== ["chartType", "interval", "seriesKey", "sourceVersion"].sort().join()
    || typeof chart.interval !== "string" || chart.interval.length < 1 || chart.interval.length > 32
    || typeof chart.chartType !== "string" || chart.chartType.length < 1 || chart.chartType.length > 32
    || typeof chart.seriesKey !== "string" || chart.seriesKey.length < 1 || chart.seriesKey.length > 1024
    || !Number.isSafeInteger(chart.sourceVersion) || chart.sourceVersion < 0) return fail();
  return { id: value.id, image: value.image, context, capturedContext, chart: { ...chart } };
}
const same = (a: ReplayNoteCaptureSave, b: ReplayNoteCaptureSave) => a.id === b.id && a.image === b.image
  && sameReplayNoteContext(a.context, b.context) && sameReplayNoteContext(a.capturedContext, b.capturedContext)
  && a.chart.interval === b.chart.interval && a.chart.chartType === b.chart.chartType
  && a.chart.seriesKey === b.chart.seriesKey && a.chart.sourceVersion === b.chart.sourceVersion;

export function createReplayNoteCaptureDraft(context: ReplayNoteContext, capture: Omit<ReplayNoteCaptureSave, "id" | "context">): ReplayNoteCaptureSave {
  return decode(JSON.stringify({ ...capture, id: "rc_" + journalClientId(), context }));
}
export function saveReplayNoteCaptureDraft(storage: Store, payload: ReplayNoteCaptureSave): void {
  const valid = decode(JSON.stringify(payload)), old = storage.getItem(key(valid.id));
  if (old !== null && !same(decode(old), valid)) throw new JournalDraftError("changed");
  storage.setItem(key(valid.id), JSON.stringify(valid));
}
export function readReplayNoteCaptureDraft(storage: Store, id: string, context: ReplayNoteContext, view: ReplayNoteContext): ReplayNoteCaptureSave | null {
  const raw = storage.getItem(key(id));
  if (raw === null) return null;
  const value = decode(raw);
  if (value.id !== id || !sameReplayNoteContext(value.context, context) || !within(value.capturedContext, view)) throw new JournalDraftError("changed");
  return value;
}
export function releaseReplayNoteCaptureDraft(storage: Store, payload: ReplayNoteCaptureSave): void {
  const raw = storage.getItem(key(payload.id));
  if (raw !== null && !same(decode(raw), payload)) throw new JournalDraftError("changed");
  storage.removeItem(key(payload.id));
}
export function attachReplayNoteCapture(fields: Record<string, string>, id: string): Record<string, string> {
  const identifiers = replayNoteScreenshotIds(fields);
  if (replayNotePendingCapture(fields) !== id) throw new JournalDraftError("changed");
  const next = [...new Set([...identifiers, id])];
  if (next.length > 2) return fail();
  const result: Record<string, string> = { ...fields, [replayNoteScreenshotField]: JSON.stringify(next) };
  delete result[replayNotePendingCaptureField];
  return result;
}
/** Copy is explicit and creates a new request; the original bytes/context remain recoverable. */
export function copyReplayNoteCaptureDraft(storage: Store, fields: Record<string, string>, original: ReplayNoteContext,
  current: ReplayNoteContext): Record<string, string> {
  const id = replayNotePendingCapture(fields);
  if (id === null) return { ...fields };
  if (!within(original, current)) throw new JournalDraftError("changed");
  const source = readReplayNoteCaptureDraft(storage, id, original, current);
  if (source === null) return { ...fields }; // An already uploaded id can be resolved through its scoped metadata.
  const copy = createReplayNoteCaptureDraft(current, { image: source.image, capturedContext: source.capturedContext, chart: source.chart });
  saveReplayNoteCaptureDraft(storage, copy);
  return { ...fields, [replayNotePendingCaptureField]: copy.id };
}
