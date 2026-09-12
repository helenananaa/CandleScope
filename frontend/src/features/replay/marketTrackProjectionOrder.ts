import type { ReplayMarketTracksResponse } from "./replayV2Types.js";

type ProjectionVersion = Pick<ReplayMarketTracksResponse, "run_id"> & {
  readonly tracks: ReadonlyArray<Pick<ReplayMarketTracksResponse["tracks"][number], "adapter_session_id" | "cursor">>;
};

/** A delayed push must not replace a newer command acknowledgement. */
export function marketTrackProjectionIsOlder(next: ProjectionVersion, current: ProjectionVersion): boolean {
  if (next.run_id !== current.run_id) return false;
  // Playback generation/tick are process-local and reset on server recovery.
  // Only persisted adapter revisions can establish this cross-stream floor.
  return next.tracks.some((track) => {
    if (track.adapter_session_id === null || track.cursor === null) return false;
    const previous = current.tracks.find((item) => item.adapter_session_id === track.adapter_session_id);
    return previous?.cursor !== null && previous?.cursor !== undefined
      && track.cursor.revision < previous.cursor.revision;
  });
}
