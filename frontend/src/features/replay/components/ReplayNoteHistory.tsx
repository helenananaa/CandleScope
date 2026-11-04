import { useEffect, useState } from "react";
import { t } from "../../../i18n/index.js";
import { sameReplayNoteContext, type ReplayNote, type ReplayNoteContext } from "../replayNotes.js";
import type { ReplayV2ApiClient } from "../replayV2Api.js";
import { ReplayNoteLinks } from "./ReplayNoteLinks.js";

export default function ReplayNoteHistory({ api, note, context, scope, asOfMs, formatTime, actualTime, onTimes }: {
  api: Pick<ReplayV2ApiClient, "noteVersionsRun">; note: ReplayNote; context: ReplayNoteContext;
  scope: string; asOfMs: number; formatTime(ms: number): string; actualTime(ms: number): string;
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
      { atTimeMs: asOfMs, beforeRevision: before, limit: 20 }, controller.signal).then(result => {
      if (controller.signal.aborted) return;
      if (!sameReplayNoteContext(result.context, context)) throw new TypeError("Replay note history context changed");
      setPage(previous => ({ versions: [...previous.versions.filter(version => version.revisionCount >= before), ...result.versions], next: result.nextBeforeRevision,
        before, attempt, error: false }));
    }).catch(() => {
      if (!controller.signal.aborted) setPage(previous => ({ ...previous, before, attempt, error: true }));
    });
    return () => controller.abort();
  }, [api, context, note.id, asOfMs, before, attempt]);
  useEffect(() => { onTimes(scope, page.versions.flatMap(version => [version.effectiveTimeMs, ...(version.links?.map(link => link.eventTimeMs) ?? [])])); }, [scope, page.versions, onTimes]);
  return <div className="replay-note-history" data-testid="replay-note-history">
    {page.versions.map(version => <div key={version.revisionCount} data-note-version={version.revisionCount}>
      <strong>{t("replay.notes.version", { version: version.revisionCount })}</strong>
      <dl><dt>{t("replay.notes.effectiveTime")}</dt><dd>{formatTime(version.effectiveTimeMs)}</dd>
        <dt>{t("replay.notes.savedTime")}</dt><dd>{actualTime(version.updatedAtMs)}</dd></dl>
      <p className="replay-note-text">{version.fields.entryBasis ?? ""}</p>
      <ReplayNoteLinks links={version.links ?? []} formatTime={formatTime} />
    </div>)}
    {loading && <p role="status">{t("replay.notes.historyLoading")}</p>}
    {page.error && !loading && <p role="alert">{t("replay.notes.historyFailed")}</p>}
    {!loading && page.error && <button type="button" onClick={() => setAttempt(value => value + 1)}>{t("replay.notes.refresh")}</button>}
    {!loading && !page.error && page.next !== null && <button type="button" onClick={() => setBefore(page.next!)}>{t("replay.notes.moreVersions")}</button>}
  </div>;
}
