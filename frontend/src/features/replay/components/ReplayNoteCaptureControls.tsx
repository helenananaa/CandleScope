import { useEffect, useRef, useState } from "react";
import { Button, Checkbox, InlineAlert } from "../../../components/ui/index.js";
import { t } from "../../../i18n/index.js";
import { attachReplayNoteCapture, createReplayNoteCaptureDraft, readReplayNoteCaptureDraft, releaseReplayNoteCaptureDraft,
  replayNotePendingCapture, replayNotePendingCaptureField, replayNoteScreenshotField, replayNoteScreenshotIds, saveReplayNoteCaptureDraft } from "../replayNoteCaptureDraft.js";
import { replayNoteView, sameReplayNoteContext, type ReplayNoteCapture, type ReplayNoteCaptureSave, type ReplayNoteContext } from "../replayNotes.js";
import type { ReplayV2ApiClient } from "../replayV2Api.js";

type Api = Pick<ReplayV2ApiClient, "saveNoteCaptureRun" | "noteCapturesRun">;
export type ReplayNoteChartCapture = (context: ReplayNoteContext) => Promise<Omit<ReplayNoteCaptureSave, "id" | "context">>;
export default function ReplayNoteCaptureControls({ api, context, view, fields, edit, captureChart, disabled, onBusy, actualTime }: {
  api: Api; context: ReplayNoteContext; view: ReplayNoteContext; fields: Record<string, string>;
  edit(update: (fields: Record<string, string>) => Record<string, string>): boolean;
  captureChart?: ReplayNoteChartCapture | undefined; disabled: boolean; onBusy(value: boolean): void; actualTime(ms: number): string;
}) {
  const [operation, setOperation] = useState<{ key: string; busy: boolean; error: boolean; draftError: boolean } | null>(null);
  const [choices, setChoices] = useState<{ key: string; values: ReplayNoteCapture[] } | null>(null);
  const [showChoices, setShowChoices] = useState(false);
  const request = useRef<AbortController | null>(null), memory = useRef<ReplayNoteCaptureSave | null>(null);
  const viewKey = JSON.stringify(view), busy = operation?.key === viewKey && operation.busy;
  useEffect(() => () => { request.current?.abort(); onBusy(false); }, [viewKey, onBusy]);
  let pending: string | null = null, selected: string[] = [], valid = true;
  try { pending = replayNotePendingCapture(fields); selected = replayNoteScreenshotIds(fields); } catch { valid = false; }
  const current = sameReplayNoteContext(context, view), available = choices?.key === viewKey ? choices.values : [];
  const within = (capture: ReplayNoteCapture) => capture.runId === context.runId && capture.trackId === context.trackId
    && capture.dataEpoch === context.dataEpoch && capture.marketTimeMs <= context.virtualTimeMs
    && capture.timelineSequence <= context.timelineSequence;
  const begin = () => {
    request.current?.abort(); const controller = new AbortController(); request.current = controller;
    setOperation({ key: viewKey, busy: true, error: false, draftError: false }); onBusy(true); return controller;
  };
  const finish = (controller: AbortController) => {
    if (request.current !== controller) return;
    onBusy(false); setOperation(value => value?.key === viewKey ? { ...value, busy: false } : value);
  };
  const complete = async (payload: ReplayNoteCaptureSave, controller: AbortController) => {
    const result = await api.saveNoteCaptureRun(context.runId, context.trackId, payload, controller.signal, replayNoteView(payload.context));
    if (controller.signal.aborted) return;
    if (!within(result.capture)) throw new TypeError("Capture exceeds the draft view");
    if (edit(value => attachReplayNoteCapture(value, result.capture.id))) {
      releaseReplayNoteCaptureDraft(localStorage, payload); memory.current = null;
    }
  };
  const capture = async () => {
    if (!captureChart || !current || disabled || !valid || selected.length >= 2 || pending) return;
    const controller = begin();
    try {
      const pixels = await captureChart(context);
      if (controller.signal.aborted) return;
      const payload = createReplayNoteCaptureDraft(context, pixels); memory.current = payload;
      if (!edit(value => ({ ...value, [replayNotePendingCaptureField]: payload.id }))) throw new Error("Capture intent draft could not be saved");
      try { saveReplayNoteCaptureDraft(localStorage, payload); }
      catch (error) { setOperation({ key: viewKey, busy: false, error: true, draftError: true }); throw error; }
      await complete(payload, controller);
    } catch { if (!controller.signal.aborted) setOperation(value => ({ key: viewKey, busy: false, error: true, draftError: value?.draftError ?? false })); }
    finally { finish(controller); }
  };
  const retry = async () => {
    if (!pending || disabled || !valid) return;
    const controller = begin();
    try {
      const payload = memory.current?.id === pending ? memory.current : readReplayNoteCaptureDraft(localStorage, pending, context, view);
      if (payload) { saveReplayNoteCaptureDraft(localStorage, payload); await complete(payload, controller); }
      else {
        const result = await api.noteCapturesRun(context.runId, context.trackId, pending, controller.signal, replayNoteView(view));
        if (controller.signal.aborted) return;
        const capture = result.captures[0];
        if (!sameReplayNoteContext(result.context, view) || !capture || !within(capture)) throw new TypeError("Capture recovery changed its view");
        edit(value => attachReplayNoteCapture(value, capture.id));
      }
    } catch { if (!controller.signal.aborted) setOperation({ key: viewKey, busy: false, error: true, draftError: false }); }
    finally { finish(controller); }
  };
  const loadChoices = async () => {
    if (!current || disabled || !valid) return;
    setShowChoices(value => !value); if (showChoices) return;
    const controller = begin();
    try {
      const result = await api.noteCapturesRun(context.runId, context.trackId, undefined, controller.signal, replayNoteView(view));
      if (controller.signal.aborted) return;
      if (!sameReplayNoteContext(result.context, view)) throw new TypeError("Capture selection changed its view");
      setChoices({ key: viewKey, values: result.captures });
    } catch { if (!controller.signal.aborted) setOperation({ key: viewKey, busy: false, error: true, draftError: false }); }
    finally { finish(controller); }
  };
  const discard = () => {
    let payload: ReplayNoteCaptureSave | null = null;
    try { payload = readReplayNoteCaptureDraft(localStorage, pending!, context, view); } catch { /* Retain unreadable material. */ }
    if (edit(value => { const next = { ...value }; delete next[replayNotePendingCaptureField]; return next; })) {
      try { if (payload) releaseReplayNoteCaptureDraft(localStorage, payload); } catch { /* Preserve conflicting recovery data. */ }
      memory.current = null; setOperation(null);
    }
  };
  return <div className="replay-note-capture-controls" data-testid="replay-note-capture-controls">
    <div className="replay-note-tool-row">
      <Button size="sm" disabled={disabled || busy || !valid || !current || !captureChart || selected.length >= 2 || pending !== null}
        onClick={() => { void capture(); }}>{t("replay.notes.capture")}</Button>
      <Button size="sm" variant="ghost" disabled={disabled || busy || !valid || !current || pending !== null}
        onClick={() => { void loadChoices(); }} aria-expanded={showChoices}>{t("replay.notes.capturesChoose")}</Button>
    </div>
    <p className="replay-note-hint">{t("replay.notes.captureHint")}</p>
    {busy && <p className="replay-notes-status" role="status">{t("replay.notes.captureBusy")}</p>}
    {(!valid || operation?.key === viewKey && operation.error) && <InlineAlert tone="danger">{t(operation?.draftError ? "replay.notes.captureDraftFailed" : "replay.notes.captureFailed")}</InlineAlert>}
    {pending && <InlineAlert tone="warning" action={<span className="replay-note-tool-row">
      <Button size="sm" disabled={disabled || busy} onClick={() => { void retry(); }}>{t("replay.notes.captureRetry")}</Button>
      <Button size="sm" variant="ghost" disabled={disabled || busy} onClick={discard}>{t("replay.notes.captureDiscard")}</Button>
    </span>}>{t("replay.notes.capturePending")}</InlineAlert>}
    {selected.length > 0 && <div className="replay-note-tool-row">
      {selected.map((id, index) => <Button size="sm" variant="ghost" key={id} disabled={disabled || busy} data-capture-id={id}
        onClick={() => edit(value => ({ ...value, [replayNoteScreenshotField]: JSON.stringify(replayNoteScreenshotIds(value).filter(item => item !== id)) }))}>
        {t("replay.notes.captureRemove", { index: index + 1 })}</Button>)}
    </div>}
    {showChoices && current && <div className="replay-note-capture-options">
      {available.length === 0 && !busy && <p className="replay-note-hint">{t("replay.notes.capturesEmpty")}</p>}
      {available.map(capture => <Checkbox key={capture.id} checked={selected.includes(capture.id)}
        disabled={disabled || busy || pending !== null || selected.length >= 2 && !selected.includes(capture.id)} onChange={() => edit(value => {
          const selected = replayNoteScreenshotIds(value), next = selected.includes(capture.id) ? selected.filter(id => id !== capture.id) : [...selected, capture.id];
          return { ...value, [replayNoteScreenshotField]: JSON.stringify(next) };
        })} label={`${actualTime(capture.savedAtMs)} · ${capture.interval} · ${capture.width}×${capture.height}`} />)}
    </div>}
  </div>;
}
