import type { ReplayStore } from "./replayStore.js";
import type { ReplayV2Command, ReplayV2CommandType, ReplayV2Json, ReplayViewerState } from "./replayV2Types.js";

/** Dispatch against stream authority, which can be ahead of React's batched view. */
export function buildReplayViewerCommand({ store, viewer, clientInstanceId, commandId, type, payload }: {
  store: Pick<ReplayStore, "getAuthoritySnapshot">;
  viewer: Pick<ReplayViewerState, "run_id"> | null;
  clientInstanceId: string;
  commandId: string;
  type: ReplayV2CommandType;
  payload: Readonly<Record<string, ReplayV2Json>>;
}): ReplayV2Command {
  const authority = store.getAuthoritySnapshot();
  if (viewer === null || !authority.hasAuthoritativeSnapshot
    || authority.connectionState !== "connected"
    || authority.virtualTimeMs === null || authority.sessionId === null) {
    throw new Error("replay.v3 viewer is not command-ready");
  }
  return {
    protocol: "replay.v3", run_id: viewer.run_id, command_id: commandId,
    client_instance_id: clientInstanceId, expected_revision: authority.revision,
    expected_cursor: {
      virtual_time_ms: authority.virtualTimeMs,
      source_sequence: authority.sourceSequence,
      revision: authority.revision,
    },
    type, payload,
  };
}

/** Visible-track promotion must wait for startup ownership and target selection. */
export function canAdmitReplayVisibleTrack({ ready, ownsController, runtimePending, viewerPending,
  controlPending, selectionPending, admissionPending, reviewing }: {
  ready: boolean;
  ownsController: boolean;
  runtimePending: boolean;
  viewerPending: boolean;
  controlPending: boolean;
  selectionPending: boolean;
  admissionPending: boolean;
  reviewing: boolean;
}): boolean {
  return ready && ownsController && !runtimePending && !viewerPending && !controlPending
    && !selectionPending && !admissionPending && !reviewing;
}
