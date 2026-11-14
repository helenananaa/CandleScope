import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Badge, Button, Disclosure, EmptyState, Field, InlineAlert, Textarea } from "../../../components/ui/index.js";
import { t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import { JournalEditor } from "../../trading-accounts/journalEditor.js";
import { replayNoteCopyBinding, replayNoteDraftBinding, visibleReplayNoteDrafts, type ReplayNoteDraft } from "../replayNoteDraft.js";
import { replayNoteView, type ReplayNote, type ReplayNotesResponse } from "../replayNotes.js";
import type { ReplayV2ApiClient } from "../replayV2Api.js";
import { ReplayNoteLinkPicker, ReplayNoteLinks } from "./ReplayNoteLinks.js";
import ReplayNoteCaptureControls, { type ReplayNoteChartCapture } from "./ReplayNoteCaptureControls.js";
import { ReplayNoteScreenshots, ReplayNoteScreenshotViewer, type ReplayNoteScreenshotSelection } from "./ReplayNoteScreenshots.js";
import { copyReplayNoteCaptureDraft, replayNotePendingCapture } from "../replayNoteCaptureDraft.js";
import ReplayNoteHistory from "./ReplayNoteHistory.js";

type Api = Pick<ReplayV2ApiClient, "notesRun" | "saveNoteRun" | "noteVersionsRun" | "noteLinkOptionsRun" | "saveNoteCaptureRun" | "noteCapturesRun" | "noteScreenshotRun">;
type Binding = ReturnType<typeof replayNoteDraftBinding>;
interface EditorTarget { note: ReplayNote | null; binding: Binding; defaults?: Record<string, string> }

function NoteEditor({ api, target, view, captureChart, actualTime, onChanged, onClose, onCopy }: {
  api: Api; target: EditorTarget; view: ReplayNotesResponse["context"]; captureChart?: ReplayNoteChartCapture | undefined; actualTime(ms: number): string; onChanged(): void; onClose(): void;
  onCopy?: (fields: Record<string, string>) => void;
}) {
  const [captureBusy, setCaptureBusy] = useState(false);
  const { binding, note } = target;
  const sameView = binding.context.reviewId === view.reviewId;
  const [editor] = useState(() => new JournalEditor<ReplayNote>({
    key: binding.key, storage: () => binding.storage,
    create: (fields, entryId) => api.saveNoteRun(binding.context.runId, binding.context.trackId,
      { id: entryId, fields, expectedRevision: 0, context: binding.context }, undefined, replayNoteView(binding.context)),
    save: (entryId, fields, expectedRevision) => api.saveNoteRun(binding.context.runId, binding.context.trackId,
      { id: entryId, fields, expectedRevision, context: binding.context }, undefined, replayNoteView(binding.context)),
    quick: async () => undefined,
  }));
  const state = useSyncExternalStore(editor.subscribe, editor.getSnapshot, editor.getSnapshot);
  useEffect(() => {
    editor.activate(); editor.initialize(note, target.defaults);
    if (target.defaults && !editor.getSnapshot().recovered) editor.edit(target.defaults);
    return () => editor.dispose();
  }, [editor, note, target.defaults]);
  const save = async (close: boolean) => {
    try { if (!sameView || captureBusy || replayNotePendingCapture(editor.getSnapshot().fields)) return; } catch { return; }
    if (await editor.flush()) { onChanged(); if (close) onClose(); }
  };
  const saveBlocked = !sameView || !state.ready || state.status === "saving" || captureBusy || state.fields.replayPendingCaptureId !== undefined;
  return <div className="replay-note-editor" data-testid="replay-note-editor">
    <Field label={t("replay.notes.body")} hint={t(binding.context.reviewNote ? "replay.notes.reviewHint" : "replay.notes.planHint")}>
      <Textarea value={state.fields.entryBasis ?? ""} disabled={!state.ready} maxLength={16_000} rows={6}
        onChange={event => editor.edit({ ...state.fields, entryBasis: event.target.value })} />
    </Field>
    <ReplayNoteLinkPicker api={api} context={binding.context} fields={state.fields}
      disabled={!sameView || !state.ready || state.status === "saving"} onChange={fields => editor.edit(fields)} />
    <ReplayNoteCaptureControls api={api} context={binding.context} view={view} fields={state.fields}
      captureChart={captureChart} disabled={!sameView || !state.ready || state.status === "saving"} onBusy={setCaptureBusy} actualTime={actualTime}
      edit={update => { try { editor.edit(update(editor.getSnapshot().fields)); return editor.getSnapshot().status !== "failed"; } catch { return false; } }} />
    {state.recovered && <InlineAlert tone="info">{t("replay.notes.recovered")}</InlineAlert>}
    {state.error != null && <InlineAlert tone="danger">{t("replay.notes.saveFailed")}</InlineAlert>}
    {onCopy && <InlineAlert tone="warning">{t("replay.notes.copyHint")}</InlineAlert>}
    <div className="replay-note-editor-actions">
      <Button size="sm" variant="primary" disabled={saveBlocked} onClick={() => { void save(false); }}>
        {t(state.status === "saving" ? "replay.notes.saving" : "replay.notes.save")}</Button>
      <Button size="sm" disabled={saveBlocked} onClick={() => { void save(true); }}>{t("replay.notes.saveClose")}</Button>
      {onCopy && <Button size="sm" disabled={!state.ready || state.status === "saving"}
        onClick={() => onCopy(state.fields)}>{t("replay.notes.copyCurrent")}</Button>}
      <Button size="sm" variant="ghost" disabled={state.status === "saving"} onClick={onClose}>{t("replay.notes.close")}</Button>
    </div>
  </div>;
}

export default function ReplayNotesPanel({ api, runId, trackId, generationKey, reviewId, reviewRevision, cursorMs, revisionKey, formatTime, onTimes, onSaved, captureChart, embedded = false }: {
  api: Api; runId: string; trackId: string; generationKey: string; cursorMs: number | null;
  reviewId: string | null; reviewRevision: number | null;
  revisionKey: string; formatTime(ms: number): string;
  embedded?: boolean;
  captureChart?: ReplayNoteChartCapture | undefined;
  onSaved?(): void;
  onTimes?(values: readonly number[]): void;
}) {
  const locale = useLocale();
  const [open, setOpen] = useState(embedded);
  const [loaded, setLoaded] = useState<{ generationKey: string; revisionKey: string; value: ReplayNotesResponse } | null>(null);
  const [error, setError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [target, setTarget] = useState<EditorTarget | null>(null);
  const [drafts, setDrafts] = useState<ReplayNoteDraft[]>([]);
  const [draftError, setDraftError] = useState(false);
  const [preview, setPreview] = useState<ReplayNoteScreenshotSelection | null>(null);
  const closePreview = useCallback(() => setPreview(null), []);
  const [historyId, setHistoryId] = useState<string | null>(null);
  const [historyTimes, setHistoryTimes] = useState<{ scope: string; values: readonly number[] }>({ scope: "", values: [] });
  const reportHistoryTimes = useCallback((scope: string, values: readonly number[]) => setHistoryTimes({ scope, values }), []);
  const sequence = useRef(0), lastStarted = useRef(0);
  const changed = useCallback(() => setRefresh(value => value + 1), []);
  const saved = useCallback(() => { changed(); onSaved?.(); }, [changed, onSaved]);
  const close = useCallback(() => { setTarget(null); changed(); }, [changed]);
  useEffect(() => {
    if (!open || cursorMs === null) return;
    const current = ++sequence.current;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      lastStarted.current = Date.now();
      api.notesRun(runId, trackId, cursorMs, controller.signal, replayNoteView({ reviewId, reviewRevision })).then(result => {
        if (controller.signal.aborted || current !== sequence.current) return;
        setLoaded({ generationKey, revisionKey, value: result }); setError(false);
        try { setDrafts(visibleReplayNoteDrafts(localStorage, result.context, cursorMs)); setDraftError(false); }
        catch { setDraftError(true); }
      }).catch(() => { if (!controller.signal.aborted && current === sequence.current) setError(true); });
    }, Math.max(0, 500 - (Date.now() - lastStarted.current)));
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [api, runId, trackId, generationKey, reviewId, reviewRevision, cursorMs, revisionKey, open, refresh]);
  const candidate = loaded?.value;
  const current = loaded?.generationKey === generationKey && candidate?.run_id === runId && candidate.track_id === trackId
    && candidate.context.reviewId === reviewId && candidate.context.reviewRevision === reviewRevision
    && cursorMs !== null && candidate.asOfMs <= cursorMs ? candidate : null;
  const settled = current !== null && loaded?.revisionKey === revisionKey
    && current.asOfMs === cursorMs && current.context.virtualTimeMs === cursorMs;
  const visibleTarget = target && current && cursorMs !== null && target.binding.context.runId === runId
    && target.binding.context.trackId === trackId && target.binding.context.dataEpoch === current.context.dataEpoch
    && target.binding.context.timelineSequence <= current.context.timelineSequence
    && target.binding.context.virtualTimeMs <= cursorMs ? target : null;
  const edit = (note: ReplayNote | null, recovered?: ReplayNoteDraft) => {
    if (!current || cursorMs === null) return;
    try {
      const binding = replayNoteDraftBinding(localStorage, current.context, cursorMs, note, recovered);
      setTarget({ note, binding }); setDraftError(false);
    } catch { setDraftError(true); }
  };
  const actualTime = (ms: number) => new Intl.DateTimeFormat(locale, { dateStyle: "short", timeStyle: "medium" }).format(ms);
  const copy = (fields: Record<string, string>) => {
    if (!settled || !current || cursorMs === null || !visibleTarget) return;
    try {
      const binding = replayNoteCopyBinding(localStorage, current.context, cursorMs, visibleTarget.binding);
      setTarget({ note: null, binding, defaults: copyReplayNoteCaptureDraft(localStorage, fields, visibleTarget.binding.context, current.context) }); setDraftError(false);
    } catch { setDraftError(true); }
  };
  const canCopy = settled && visibleTarget !== null && current !== null
    && (visibleTarget.binding.context.runRevision !== current.context.runRevision
      || visibleTarget.binding.context.timelineSequence !== current.context.timelineSequence
      || visibleTarget.binding.context.reviewId !== current.context.reviewId
      || visibleTarget.binding.context.reviewRevision !== current.context.reviewRevision
      || visibleTarget.binding.context.virtualTimeMs !== current.context.virtualTimeMs);
  const historyNote = settled && current && open && !visibleTarget ? current.notes.find(note => note.id === historyId) : null;
  const historyScope = historyNote && current ? JSON.stringify([current.context, current.asOfMs, historyNote.id, historyNote.revisionCount]) : "";
  useEffect(() => {
    onTimes?.([...(current?.notes.flatMap(note => [note.marketTimeMs, note.effectiveTimeMs, ...(note.links?.map(link => link.eventTimeMs) ?? []), ...(note.screenshots?.map(capture => capture.marketTimeMs) ?? [])]) ?? []),
      ...(historyScope && historyTimes.scope === historyScope ? historyTimes.values : [])]);
  }, [current, historyScope, historyTimes, onTimes]);
  const visibleDrafts = drafts.filter(draft => current && cursorMs !== null && draft.context.virtualTimeMs <= cursorMs
    && draft.context.timelineSequence <= current.context.timelineSequence
    && draft.context.dataEpoch === current.context.dataEpoch);
  const body = <div className="replay-notes-body">
    <div className="replay-notes-toolbar">
      <Button size="sm" variant="primary" disabled={!settled || visibleTarget !== null} onClick={() => edit(null)}>
        {t(current?.context.reviewNote ? "replay.notes.addReview" : "replay.notes.add")}</Button>
      <Button size="sm" variant="ghost" onClick={changed}>{t("replay.notes.refresh")}</Button>
    </div>
    {error && <InlineAlert tone="danger">{t("replay.notes.loadFailed")}</InlineAlert>}
    {!settled && !error && <p className="replay-notes-status" role="status">{t("replay.notes.loading")}</p>}
    {draftError && <InlineAlert tone="danger">{t("replay.notes.draftFailed")}</InlineAlert>}
    {visibleTarget ? <NoteEditor key={visibleTarget.binding.key} api={api} target={visibleTarget} view={current!.context} captureChart={captureChart} actualTime={actualTime} onChanged={saved} onClose={close} {...(canCopy ? { onCopy: copy } : {})} />
      : <>
        {visibleDrafts.length > 0 && <div className="replay-note-drafts">
          {visibleDrafts.map(draft =>
            <Button size="sm" key={draft.key} onClick={() => edit(current?.notes.find(note => note.id === draft.noteId) ?? null, draft)}>
              {t("replay.notes.recover")} · {formatTime(draft.context.virtualTimeMs)}</Button>)}
        </div>}
        {current && current.notes.length === 0 && <EmptyState compact title={t("replay.notes.empty")} />}
        {current && current.notes.length > 0 && <ul className="replay-note-list">
          {current.notes.map(note => <li key={note.id} className="replay-note-card" data-note-id={note.id}>
            <header className="replay-note-head">
              <Badge tone={note.reviewNote ? "accent" : "neutral"}>{t(note.reviewNote ? "replay.notes.review" : "replay.notes.original")}</Badge>
              <time className="replay-note-time" title={t("replay.notes.virtualTime")}>{formatTime(note.marketTimeMs)}</time>
            </header>
            <p className="replay-note-text">{note.fields.entryBasis ?? ""}</p>
            <ReplayNoteLinks links={note.links ?? []} formatTime={formatTime} />
            <ReplayNoteScreenshots note={note} context={current.context} formatTime={formatTime} onOpen={setPreview} disabled={!settled} />
            <footer className="replay-note-foot">
              <small className="replay-note-saved">{t("replay.notes.savedTime")} {actualTime(note.updatedAtMs)}</small>
              <span className="replay-note-actions">
              <Button size="sm" variant="ghost" disabled={!settled || Boolean(current.context.reviewNote && !note.reviewNote)} onClick={() => edit(note)}>{t("replay.notes.edit")}</Button>
              <Button size="sm" variant="ghost" disabled={!settled} aria-expanded={historyNote?.id === note.id}
                onClick={() => setHistoryId(value => value === note.id ? null : note.id)}>{t("replay.notes.history")}</Button>
              </span>
            </footer>
            {historyNote?.id === note.id && <ReplayNoteHistory key={historyScope} api={api} note={note} context={current.context}
              scope={historyScope} asOfMs={current.asOfMs} formatTime={formatTime} actualTime={actualTime} onTimes={reportHistoryTimes} onImage={setPreview} />}
          </li>)}
        </ul>}
      </>}
  </div>;
  return <section className="replay-notes-panel" aria-label={t("replay.notes.title")} data-testid="replay-notes-panel" data-embedded={embedded ? "true" : undefined}>
    {embedded ? body : <Disclosure summary={t("replay.notes.title")} open={open} onToggle={setOpen}>
      {open && body}
    </Disclosure>}
    {preview && open && !visibleTarget && settled && current && preview.contextKey === JSON.stringify(current.context) && <ReplayNoteScreenshotViewer
      key={JSON.stringify([preview.contextKey, preview.noteId, preview.revision, preview.capture.id])} api={api} selection={preview}
      context={current.context} formatTime={formatTime} actualTime={actualTime} onClose={closePreview} />}
  </section>;
}
