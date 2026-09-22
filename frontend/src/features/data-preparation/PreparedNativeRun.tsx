import { useEffect, useState } from "react";
import { t } from "../../i18n/index.js";
import { nativeApi, nativeTerminal, type NativeRun } from "../backtest/native/nativeBacktestApi.js";
import { NativeStrategyReport } from "../backtest/native/NativeStrategyReport.js";
import "../backtest/native/nativeStrategy.css";

/** Reopen the engine-owned run without restoring or overwriting an editor draft. */
export default function PreparedNativeRun({ initial, onClose }: { initial: NativeRun; onClose(): void }) {
  const [run, setRun] = useState<NativeRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    setRun(null);
    setError(null);
    const refresh = async () => {
      try {
        const path = initial.execution_mode === "CANDLESCOPE" ? "/external/runs" : "/native/runs";
        const current = await nativeApi<NativeRun>(`${path}/${encodeURIComponent(initial.run_id)}`, undefined, undefined, controller.signal);
        if (controller.signal.aborted) return;
        setRun(current);
        if (!nativeTerminal(current.state)) timer = setTimeout(() => void refresh(), 1000);
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : String(cause));
      }
    };
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [initial.run_id, initial.execution_mode, attempt]);
  return <section className="native-strategy-panel" aria-label={t("native.history")}>
    <button type="button" onClick={onClose}>{t("backtest.close")}</button>
    <p>{initial.run_id}</p>
    {error ? <p role="alert">{error} <button type="button" onClick={() => setAttempt((value) => value + 1)}>{t("shell.retry")}</button></p>
      : !run && <p role="status">{t("native.loading")}</p>}
    {run && <>
      <p role="status">{run.state}</p>
      {run.error && <p role="alert">{run.error.message}</p>}
      {run.config && <details><summary>{t("native.source")}</summary><pre>{run.config.source}</pre></details>}
      {run.result && <NativeStrategyReport key={run.run_id} run={run} />}
    </>}
  </section>;
}
