import { useEffect, useState } from "react";
import { Button, InlineAlert } from "../../../components/ui/index.js";
import { t } from "../../../i18n/index.js";
import { replayNoteView, sameReplayNoteContext, type ReplayNote, type ReplayNoteContext } from "../replayNotes.js";
import type { ReplayV2ApiClient } from "../replayV2Api.js";
import { ReplayNoteScreenshots, type ReplayNoteScreenshotSelection } from "./ReplayNoteScreenshots.js";
import { ReplayNoteLinks } from "./ReplayNoteLinks.js";

export default function ReplayNoteHistory({ api, note, context, scope, asOfMs, formatTime, actualTime, onTimes, onImage }: {
  api: Pick<ReplayV2ApiClient, "noteVersionsRun">; note: ReplayNote; context: ReplayNoteContext;
  scope: string; asOfMs: number; formatTime(ms: number): string; actualTime(ms: number): string;
  onImage(selection: ReplayNoteScreenshotSelection): void;
  onTimes(scope: string, values: readonly number[]): void;
}) {
  const [before, setBefore] = useState(note.revisionCount + 1);
  const [attempt, setAttempt] = useState(0);
  const [page, setPage] = useState<{ versions: ReplayNote[]; next: number | null; before: number; attempt: number; error: boolean }>(
    { versions: [], next: null, before: 0, attempt: -1, error: false });
  const loading = page.before !== before || page.attempt !== attempt;
  useEffect(() => {
    const controller = new AbortController();
    api.noteVersionsRun(context.runId, context.trackId, note.id,
      { atTimeMs: asOfMs, beforeRevision: before, limit: 20 }, controller.signal, replayNoteView(context)).then(result => {
      if (controller.signal.aborted) return;
      if (!sameReplayNoteContext(result.context, context)) throw new TypeError("Replay note history context changed");
      setPage(previous => ({ versions: [...previous.versions.filter(version => version.revisionCount >= before), ...result.versions], next: result.nextBeforeRevision,
        before, attempt, error: false }));
    }).catch(() => {
      if (!controller.signal.aborted) setPage(previous => ({ ...previous, before, attempt, error: true }));
    });
    return () => controller.abort();
  }, [api, context, note.id, asOfMs, before, attempt]);
  useEffect(() => { onTimes(scope, page.versions.flatMap(version => [version.effectiveTimeMs, ...(version.links?.map(link => link.eventTimeMs) ?? []), ...(version.screenshots?.map(capture => capture.marketTimeMs) ?? [])])); }, [scope, page.versions, onTimes]);
  return <div className="replay-note-history" data-testid="replay-note-history">
    {page.versions.map(version => <div key={version.revisionCount} className="replay-note-version" data-note-version={version.revisionCount}>
      <header className="replay-note-head">
        <strong>{t("replay.notes.version", { version: version.revisionCount })}</strong>
        <time className="replay-note-time" title={t("replay.notes.effectiveTime")}>{formatTime(version.effectiveTimeMs)}</time>
      </header>
      <p className="replay-note-text">{version.fields.entryBasis ?? ""}</p>
      <ReplayNoteLinks links={version.links ?? []} formatTime={formatTime} />
      <ReplayNoteScreenshots note={version} context={context} formatTime={formatTime} onOpen={onImage} />
      <small className="replay-note-saved">{t("replay.notes.savedTime")} {actualTime(version.updatedAtMs)}</small>
    </div>)}
    {loading && <p className="replay-notes-status" role="status">{t("replay.notes.historyLoading")}</p>}
    {page.error && !loading && <InlineAlert tone="danger" action={<Button size="sm" onClick={() => setAttempt(value => value + 1)}>{t("replay.notes.refresh")}</Button>}>
      {t("replay.notes.historyFailed")}</InlineAlert>}
    {!loading && !page.error && page.next !== null && <Button size="sm" variant="ghost" onClick={() => setBefore(page.next!)}>{t("replay.notes.moreVersions")}</Button>}
  </div>;
}
