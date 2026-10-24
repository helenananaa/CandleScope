import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import NativeStrategyPanel from "../../../src/features/backtest/native/NativeStrategyPanel.js";
import type { NativeRun } from "../../../src/features/backtest/native/nativeBacktestApi.js";
import { normalizeNativeStrategies, type NativeStrategyCollection } from "../../../src/features/backtest/native/nativeStrategyCollection.js";
import "../../../src/styles/tokens.css";
import "../../../src/features/backtest/chart-tester/strategyDock.css";
import { setLocaleAsync } from "../../../src/i18n/index.js";

const response = await fetch("/api/harness/bootstrap");
const payload: unknown = await response.json();
if (!payload || typeof payload !== "object" || !("source" in payload) || typeof payload.source !== "string"
  || !("dataset_id" in payload) || typeof payload.dataset_id !== "string"
  || !("data_epoch" in payload) || typeof payload.data_epoch !== "string") throw new Error("Invalid acceptance bootstrap");
const bootstrap = {source: payload.source, dataset_id: payload.dataset_id, data_epoch: payload.data_epoch};
await setLocaleAsync("zh-CN");
const automatic = new URLSearchParams(location.search).has("automatic");
const scope = automatic ? "pine-host-automatic" : "pine-host-direct";
const key = `${scope}:${bootstrap.dataset_id}`;
localStorage.setItem(`candlescope.native-tab:${scope}:CANDLESCOPE`, "settings");
const initial: NativeStrategyCollection = {activeId:"default",items:[{id:"default",name:"Host acceptance",language:"pine",executionMode:"CANDLESCOPE",runs:{},drafts:{
  "pine:CANDLESCOPE":JSON.stringify({source:bootstrap.source,parameters:"{}",historyStart:"1970-01-01",historyEnd:"1970-01-05",
    advanced:{contexts:[],magnifier:null,libraries:"{}",priceTickSize:".1"}}),
  "execution:pine:CANDLESCOPE":JSON.stringify({hostSettings:{initial_balance:10000,slippage_bps:0,taker_fee_bps:10,price_tick:.1},
    fidelity:"BAR_APPROX",fillRecalculation:true,costSensitivityMode:"AUTO",uploaded:false,
    account:{accountModel:"LINEAR_PERP_ONE_WAY_V2",leverage:10,fundingMode:"OFF",participationEnabled:true,participationRate:.05,uploaded:true}})
}}]};
export function Harness(): React.ReactElement {
  const [collection,setCollection]=useState<NativeStrategyCollection>(()=>{
    const saved: unknown = JSON.parse(localStorage.getItem(key)||JSON.stringify(initial));
    return normalizeNativeStrategies(saved);
  });
  const [run,setRun]=useState<NativeRun | null>(null);
  return <main><h1>Pine Host controlled entry acceptance · {automatic ? "automatic preparation" : "direct frozen dataset"}</h1>
    <p>Synthetic data. Production Workbench, API, interpreter, account and replay components.</p>
    <div className="acceptance-controls"><NativeStrategyPanel session={{exchange:"binance",marketType:"futures",symbol:"BTCUSDT",interval:automatic?"1d":"1m"}}
      cellScope={scope} dataset={automatic?undefined:{datasetId:bootstrap.dataset_id,dataEpoch:bootstrap.data_epoch}}
      nativeStrategies={collection} onNativeStrategiesChange={next=>{setCollection(next);localStorage.setItem(key,JSON.stringify(next));}}
      onClose={()=>{}} active docked onRunChange={setRun}/></div>
    <pre id="receipt">{JSON.stringify(run?{runId:run.run_id,state:run.state,error:run.error,
      fillModel:run.result?.fill_model,account:run.result?.account_model,quantities:run.result?.trades.map(r=>r.qty),
      costMode:run.config?.cost_sensitivity_mode,costStatus:run.result?.cost_sensitivity?.status}:null)}</pre>
  </main>;
}
createRoot(document.getElementById("root")!).render(<Harness/>);
