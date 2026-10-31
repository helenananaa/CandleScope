import { nativeApi, type NativeRun } from "./nativeBacktestApi.js";

type UnchangedRun = Omit<NativeRun, "config" | "result"> & { run_unchanged: true };

export async function pollNativeRun(current: NativeRun, signal?: AbortSignal): Promise<NativeRun> {
  const route = current.execution_mode === "CANDLESCOPE" ? "external" : "native";
  const value = await nativeApi<NativeRun | UnchangedRun>(
    `/${route}/runs/${encodeURIComponent(current.run_id)}?if_state=${encodeURIComponent(current.state)}`, undefined, undefined, signal);
  if ("run_unchanged" in value) {
    if (value.run_id !== current.run_id || value.state !== current.state) {
      throw new Error("Native run polling state differs from its cached report");
    }
    const { run_unchanged: _, ...header } = value;
    return { ...current, ...header };
  }
  return value;
}
