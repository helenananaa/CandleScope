import type { StrategyDataManager } from "../../market-data/manager/strategyDataManager.js";
import { nativeApi, type NativeRun } from "./nativeBacktestApi.js";

/**
 * Follow a native or CandleScope-matched run through the run facade's commit-driven
 * stream (ADR-BACKTEST-015 P2b) instead of polling it.
 *
 * Each committed state change updates the run's header; once the run finishes, its
 * full record (result or error) is read once. Aborting stops watching, never the run.
 */
export async function watchNativeRun(manager: Pick<StrategyDataManager, "watchRun">, current: NativeRun,
  onRun: (run: NativeRun) => void, signal?: AbortSignal): Promise<NativeRun> {
  let latest = current;
  const terminal = await manager.watchRun(current.run_id, (status) => {
    if (status.terminal || status.source_state === latest.state) return;
    latest = { ...latest, state: status.source_state };
    onRun(latest);
  }, signal);
  const route = current.execution_mode === "CANDLESCOPE" ? "external" : "native";
  const record = await nativeApi<NativeRun>(`/${route}/runs/${encodeURIComponent(current.run_id)}`, undefined, undefined, signal);
  if (record.run_id !== current.run_id || record.state !== terminal.source_state) {
    throw new Error("Native run record differs from its finished status");
  }
  onRun(record);
  return record;
}
