import { nativeApi } from "./nativeBacktestApi.js";
import type { NativeReplayRecord } from "./NativeReplayControls.js";

type UnchangedReplay = Omit<NativeReplayRecord, "result"> & { result_unchanged: true };

export async function pollNativeReplay(current: NativeReplayRecord, signal?: AbortSignal): Promise<NativeReplayRecord> {
  const value = await nativeApi<NativeReplayRecord | UnchangedReplay>(
    `/native/replays/${encodeURIComponent(current.replay_id)}?if_revision=${current.revision}`, undefined, undefined, signal);
  if ("result_unchanged" in value) {
    if (value.replay_id !== current.replay_id || value.revision !== current.revision || value.cursor !== current.cursor) {
      throw new Error("Replay polling revision differs from its cached report");
    }
    const { result_unchanged: _, ...header } = value;
    return { ...header, result: current.result };
  }
  return value;
}
