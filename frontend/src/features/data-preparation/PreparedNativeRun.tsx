import { describeError } from "../../i18n/serverErrors.js";
import { useEffect, useState } from "react";
import { Button } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import { nativeTerminal, type NativeRun } from "../backtest/native/nativeBacktestApi.js";
import { useStrategyDataManager } from "../market-data/useStrategyDataManager.js";
import { NativeStrategyReport } from "../backtest/native/NativeStrategyReport.js";
import "../backtest/native/nativeStrategy.css";

/** Reopen the engine-owned run without restoring or overwriting an editor draft. */
export default function PreparedNativeRun({ initial, onClose }: { initial: NativeRun; onClose(): void }) {
  const manager = useStrategyDataManager();
  const [run, setRun] = useState<NativeRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!manager) return;
    const controller = new AbortController();
    setRun(null);
    setError(null);
    const mode = initial.execution_mode === "CANDLESCOPE" ? "CANDLESCOPE" : "NATIVE";
    // Read once, then follow the run's committed status instead of polling it.
    const follow = async () => {
      try {
        const current = await manager.loadNativeRun(mode, initial.run_id, controller.signal);
        if (controller.signal.aborted) return;
        setRun(current);
        if (!nativeTerminal(current.state)) {
          await manager.followNativeRun(current, (value) => { if (!controller.signal.aborted) setRun(value); }, controller.signal);
        }
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? describeError(cause, cause.message) : String(cause));
      }
    };
    void follow();
    return () => controller.abort();
  }, [manager, initial.run_id, initial.execution_mode, attempt]);
  return <section className="native-strategy-panel" aria-label={t("native.history")}>
    <Button size="sm" onClick={onClose}>{t("backtest.close")}</Button>
    <p>{initial.run_id}</p>
    {error ? <p role="alert">{error} <Button size="sm" onClick={() => setAttempt((value) => value + 1)}>{t("shell.retry")}</Button></p>
      : !run && <p role="status">{t("native.loading")}</p>}
    {run && <>
      <p role="status">{run.state}</p>
      {run.error && <p role="alert">{run.error.message}</p>}
      {run.config && <details><summary>{t("native.source")}</summary><pre>{run.config.source}</pre></details>}
      {run.result && <NativeStrategyReport key={run.run_id} run={run} />}
    </>}
  </section>;
}
