import { useEffect, useEffectEvent, useRef, useState } from "react";
import { floorIntervalTime } from "../../utils/intervalTimeline.js";
import type { ReplayNote, ReplayNotesResponse } from "./replayNotes.js";
import type { ReplayV2ApiClient } from "./replayV2Api.js";

export interface ReplayChartNoteBinding {
  runId: string;
  trackId: string;
  dataEpoch: string;
  reviewId: string | null;
  reviewRevision: number | null;
  timelineSequence: number | null;
}

const EMPTY_NOTES: readonly ReplayNote[] = [];

export function replayChartNoteVersions(
  value: ReplayNotesResponse | undefined,
  binding: ReplayChartNoteBinding | null,
  cutoffMs: number | null,
) {
  if (!value || !binding || cutoffMs === null || value.asOfMs > cutoffMs) return EMPTY_NOTES;
  const context = value.context;
  if (context.runId !== binding.runId || context.trackId !== binding.trackId || context.dataEpoch !== binding.dataEpoch
    || context.reviewId !== binding.reviewId || context.reviewRevision !== binding.reviewRevision
    || (binding.timelineSequence !== null && context.timelineSequence !== binding.timelineSequence)) return EMPTY_NOTES;
  return value.notes;
}

export function replayChartNotePoints(
  versions: ReturnType<typeof replayChartNoteVersions>,
  interval: string,
  closedBarClock: boolean,
  hasBar: (time: number) => boolean,
  label: (reviewNote: boolean) => string,
) {
  return versions.flatMap(note => {
    // A BAR replay advances to the closed candle's exclusive end. The
    // candle starting at that exact instant has not been revealed yet.
    const anchorMs = note.marketTimeMs - (closedBarClock ? 1 : 0);
    const time = floorIntervalTime(interval, Math.floor(anchorMs / 1_000));
    return time !== null && hasBar(time) ? [{
      id: note.id, revision: note.revisionCount, time,
      shape: "circle", color: note.reviewNote ? "#a855f7" : "#d97706",
      text: label(note.reviewNote), position: "above",
    }] : [];
  });
}

export function useReplayChartNoteVersions(
  api: Pick<ReplayV2ApiClient, "notesRun">,
  binding: ReplayChartNoteBinding | null,
  cutoffMs: number | null,
  generation: number,
  savedRevision: number,
) {
  const scope = binding && JSON.stringify([binding.runId, binding.trackId, binding.dataEpoch,
    binding.reviewId, generation]);
  const key = scope && JSON.stringify([scope, binding?.reviewRevision, binding?.timelineSequence, savedRevision]);
  const runId = binding?.runId;
  const trackId = binding?.trackId;
  const [loaded, setLoaded] = useState<{ key: string; value: ReplayNotesResponse }>();
  const wake = useRef<(() => void) | null>(null);
  const latest = useEffectEvent(() => ({ scope, key, cutoffMs }));

  // Coalesce cursor changes while a read is in flight. Playback can move
  // faster than the read without repeatedly aborting every response.
  useEffect(() => {
    if (!scope || !runId || !trackId) return;
    const controller = new AbortController();
    let timer: number | undefined;
    let pending = false;
    let lastStarted = 0;
    let requested: { key: string; cutoffMs: number } | undefined;
    const schedule = () => {
      const target = latest();
      if (controller.signal.aborted || pending || timer !== undefined
        || target.scope !== scope || !target.key || target.cutoffMs === null
        || (requested?.key === target.key && requested.cutoffMs === target.cutoffMs)) return;
      timer = window.setTimeout(read, Math.max(0, 500 - (Date.now() - lastStarted)));
    };
    const read = () => {
      timer = undefined;
      const target = latest();
      if (target.scope !== scope || !target.key || target.cutoffMs === null) return;
      requested = { key: target.key, cutoffMs: target.cutoffMs };
      pending = true;
      lastStarted = Date.now();
      const requestKey = requested.key;
      void api.notesRun(runId, trackId, requested.cutoffMs, controller.signal).then(value => {
        if (!controller.signal.aborted && latest().key === requestKey) setLoaded({ key: requestKey, value });
      }).catch(() => {
        if (!controller.signal.aborted && latest().key === requestKey) setLoaded(undefined);
      }).finally(() => { pending = false; schedule(); });
    };
    wake.current = schedule;
    schedule();
    return () => {
      wake.current = null;
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [api, scope, runId, trackId]);
  useEffect(() => { wake.current?.(); }, [scope, key, cutoffMs]);

  return replayChartNoteVersions(loaded?.key === key ? loaded?.value : undefined, binding, cutoffMs);
}
