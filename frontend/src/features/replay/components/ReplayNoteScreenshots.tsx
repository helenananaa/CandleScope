import { useEffect, useMemo, useRef, useState } from "react";
import { t } from "../../../i18n/index.js";
import { replayNoteView, parseReplayNoteContext, sameReplayNoteContext, type ReplayNote, type ReplayNoteCapture, type ReplayNoteContext } from "../replayNotes.js";
import type { ReplayV2ApiClient } from "../replayV2Api.js";

export interface ReplayNoteScreenshotSelection { noteId: string; revision: number; capture: ReplayNoteCapture; contextKey: string }
export function ReplayNoteScreenshots({ note, context, formatTime, onOpen, disabled = false }: {
  note: ReplayNote; context: ReplayNoteContext; formatTime(ms: number): string;
  onOpen(selection: ReplayNoteScreenshotSelection): void; disabled?: boolean;
}) {
  return (note.screenshots?.length ?? 0) > 0 ? <div className="replay-note-screenshots" data-testid="replay-note-screenshots">
    {note.screenshots!.map((capture, index) => <button type="button" key={capture.id} disabled={disabled}
      data-capture-id={capture.id} onClick={() => onOpen({ noteId: note.id, revision: note.revisionCount, capture, contextKey: JSON.stringify(context) })}>
      {t("replay.notes.captureView", { index: index + 1 })} · {formatTime(capture.marketTimeMs)}</button>)}
  </div> : null;
}

/** One dialog per note panel bounds decoded image memory across long histories. */
export function ReplayNoteScreenshotViewer({ api, selection, context, formatTime, actualTime, onClose }: {
  api: Pick<ReplayV2ApiClient, "noteScreenshotRun">; selection: ReplayNoteScreenshotSelection; context: ReplayNoteContext;
  formatTime(ms: number): string; actualTime(ms: number): string; onClose(): void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const contextKey = JSON.stringify(context), expected = useMemo(() => parseReplayNoteContext(JSON.parse(contextKey)), [contextKey]);
  const [attempt, setAttempt] = useState(0), [loaded, setLoaded] = useState<{ image: string | null; error: boolean } | null>(null);
  const { noteId, revision, capture } = selection, captureKey = JSON.stringify(capture);
  useEffect(() => { const value = dialog.current; value?.showModal(); return () => value?.close(); }, []);
  useEffect(() => {
    const controller = new AbortController();
    api.noteScreenshotRun(expected.runId, expected.trackId, noteId, revision, capture.id, controller.signal, replayNoteView(expected)).then(result => {
      if (controller.signal.aborted) return;
      if (!sameReplayNoteContext(result.context, expected) || JSON.stringify(result.capture) !== captureKey)
        throw new TypeError("Replay note image context changed");
      setLoaded({ image: result.image, error: false });
    }).catch(() => { if (!controller.signal.aborted) setLoaded({ image: null, error: true }); });
    return () => controller.abort();
  }, [api, expected, noteId, revision, capture.id, captureKey, attempt]);
  return <dialog ref={dialog} className="replay-note-screenshot-viewer" aria-label={t("replay.notes.captureTitle")}
    onCancel={event => { event.preventDefault(); onClose(); }}>
    <div className="replay-note-actions"><strong>{t("replay.notes.version", { version: revision })}</strong>
      <button type="button" onClick={onClose}>{t("replay.notes.close")}</button></div>
    <p>{t("replay.notes.captureTime")} · {formatTime(capture.marketTimeMs)} · {capture.interval}</p>
    <p>{t("replay.notes.savedTime")} · {actualTime(capture.savedAtMs)}</p>
    {loaded === null && <p role="status">{t("replay.notes.captureBusy")}</p>}
    {loaded?.image && <img src={loaded.image} alt={t("replay.notes.captureAlt", { time: formatTime(capture.marketTimeMs) })}
      onLoad={event => { if (event.currentTarget.naturalWidth !== capture.width || event.currentTarget.naturalHeight !== capture.height)
        setLoaded({ image: null, error: true }); }} onError={() => setLoaded({ image: null, error: true })} />}
    {loaded?.error && <><p role="alert">{t("replay.notes.captureLoadFailed")}</p><button type="button"
      onClick={() => { setLoaded(null); setAttempt(value => value + 1); }}>{t("replay.notes.refresh")}</button></>}
  </dialog>;
}
