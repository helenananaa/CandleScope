import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { setLocaleAsync } from "../../../src/i18n/index.js";
import { StrategyDataManager } from "../../../src/features/market-data/manager/strategyDataManager.js";
import type { ContinuousObservation } from "../../../src/features/market-data/manager/continuousStrategyDataManager.js";
import type { ContinuousCapabilities } from "../../../src/features/backtest/continuous/continuousTypes.js";
import ContinuousRepairPanel from "../../../src/features/backtest/continuous/ContinuousRepairPanel.js";
import "../../../src/styles/tokens.css";
import "../../../src/features/backtest/continuous/continuousStrategy.css";

const backend = String(import.meta.env.VITE_BACKTEST_API_BASE).replace(/\/api\/v1\/backtests$/, "");
const response = await fetch(backend+"/_qa/bootstrap"), bootstrap = await response.json() as { run_id: string };
await setLocaleAsync("zh-CN");
const manager = new StrategyDataManager();
let latest: ContinuousObservation | null = null;
Object.assign(window, { continuousRepairQA: { inspect: () => latest, diagnostics: () => manager.continuous.diagnostics() } });

function Fixture() {
  const [state, setState] = useState<ContinuousObservation | null>(null), [caps, setCaps] = useState<ContinuousCapabilities | null>(null);
  const [shown, setShown] = useState(true);
  useEffect(() => {
    const abort = new AbortController();
    void manager.continuous.capabilities(abort.signal).then(setCaps);
    const release = manager.continuous.observe(bootstrap.run_id, (value) => { latest = value; setState(value); });
    return () => { abort.abort(); release(); };
  }, []);
  const view = state?.result;
  return <main>
    <h1>连续策略历史修复 · 受控浏览器验收</h1>
    <p className="fixture-note">合成 BTCUSDT 1m 数据，实际 SDK Python、账户引擎、Manager 和 HTTP/WS；未连接公开行情。这是组件与服务验收，不是安装包验收。</p>
    <div className="fixture-account" aria-label="已提交账户">
      <span>账户：{view?.identity.id}</span><span>状态：{view?.run.phase}</span><span>已处理：{view?.identity.sequence}</span>
      <span>数据：{view?.identity.data_revision.slice(-8)}</span><span>过期：{String(view?.stale)}</span>
    </div>
    <div className="fixture-tools"><button type="button" onClick={() => setShown((value) => !value)}>{shown ? "关闭修复视图" : "重新打开修复视图"}</button></div>
    {shown && view && <ContinuousRepairPanel key={view.identity.id} manager={manager.continuous} view={view}
      repair={state?.repair ?? null} active available={!!caps?.execution_enabled && !!caps.repair_available && !!caps.python_editor_authorized} />}
    {state?.error && <p role="alert">{state.error.message}</p>}
  </main>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);
