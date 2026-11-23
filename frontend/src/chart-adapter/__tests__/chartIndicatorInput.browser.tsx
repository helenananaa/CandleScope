import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import { useLayoutEffect } from "react";
import SingleChartPanes from "../../components/SingleChartPanes.js";
import { MarketDataWorkspaceProvider } from "../../features/market-data/MarketDataWorkspaceProvider.js";
import { SYNTHETIC_TRANSFORMS, type BackendSyntheticSource, type SyntheticTransform, type SyntheticOrigin } from "../../features/market-data/synthetic/syntheticSeries.js";
import { SeriesWindowStore } from "../../features/market-data/window/seriesWindowStore.js";
import { capturedSyntheticSource } from "../../features/market-data/synthetic/capturedSyntheticSource.js";
import { replaySyntheticSource } from "../../features/replay/replaySyntheticSource.js";
import { chartIndicatorSelection } from "../../features/indicators/chartIndicatorInput.js";
import { useChartIndicatorRuntime } from "../../features/indicators/useChartIndicatorRuntime.js";
import type { IndicatorRuntime } from "../../features/indicators/indicatorRuntimeContract.js";
import type { IndicatorDefinition } from "../../features/indicators/indicatorTypes.js";
import type { KlineBar } from "../../features/market-data/marketDataTypes.js";
import { API_BASE } from "../../services/apiConfig.js";
import { useChartSurfaceRuntime } from "../useChartSurfaceRuntime.js";

function assert(value: unknown, message: string): asserts value { if (!value) throw new Error(message); }
const sleep = (ms:number)=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(predicate:()=>boolean,message:string) {
  const deadline=performance.now()+20_000;
  while(!predicate()) { assert(performance.now()<deadline,message); await sleep(25); }
}

interface Capture { origin: Extract<SyntheticOrigin, { kind: "REPLAY" }>; rows: KlineBar[] }

export async function checkChartIndicators() {
  const live=await(await fetch(`${API_BASE}/fixture/bars`)).json() as { rows: KlineBar[] };
  const pinned=await(await fetch(`${API_BASE}/fixture/pinned`)).json() as { replay: Capture };
  const market={exchange:"binance",marketType:"spot",symbol:"BTCUSDT",interval:"1m"};
  // The key must match the regular source identity; captured origins explicitly name it.
  const reader=new SeriesWindowStore({seriesKey:"indicator-captured"});
  reader.replace(live.rows);
  let source:BackendSyntheticSource=capturedSyntheticSource(market,reader.seriesKey,"indicator-browser",Date.now())!;
  let transform:SyntheticTransform="renko", box=2;
  let runtime:IndicatorRuntime|null=null;
  let surface:ReturnType<typeof useChartSurfaceRuntime>|null=null;
  const definitions:IndicatorDefinition[]=[
    {id:"ma",kind:"builtin",engineName:"MA",params:{period:2}},
    {id:"js",kind:"script",language:"frontend-js",script:'plot("JS MA", bars.map((bar,i)=>i? (bar.close+bars[i-1].close)/2:null), {pane:"main"}); plot("Clock", bars.map(bar=>bar.time));'},
  ];
  const persistence={controlled:true,load:()=>definitions,save:(list:IndicatorDefinition[])=>{assert(list.every(item=>!item.executionTarget),"chart mode overwrote durable execution ownership");}};
  const sockets:string[]=[],messages:Array<Record<string,unknown>>=[];
  const Socket=window.WebSocket;
  window.WebSocket=class extends Socket {
    constructor(url:string|URL,protocols?:string|string[]) {
      super(url,protocols);sockets.push(String(url));
      this.addEventListener("message",event=>messages.push(JSON.parse(String(event.data)) as Record<string,unknown>));
    }
  };
  const host=document.createElement("div"),style=document.createElement("style");
  host.style.cssText="width:900px;height:600px;position:relative;display:flex";
  style.textContent=".chart-area{position:relative;flex:1;height:100%;min-width:0}.chart-pane{position:absolute;inset:0}";
  document.body.append(host);document.head.append(style);
  const root=createRoot(host);
  function Probe() {
    const appearance={chartType:transform,renkoBoxSizeMode:"traditional" as const,renkoBoxSize:box,
      pointFigureBoxSizeMode:"traditional" as const,pointFigureBoxSize:box,pointFigureReversalAmount:2,
      kagiReversalMode:"traditional" as const,kagiReversalAmount:box,lineBreakNumberOfLines:2};
    const indicators=useChartIndicatorRuntime({chart:chartIndicatorSelection(source,reader,appearance),
      autoAddVolume:false,chartData:reader.snapshot(),datasetKey:reader.seriesKey!,seriesReady:1,
      exchange:source.exchange,marketType:source.marketType,symbol:source.symbol,interval:source.interval,
      realtimeEnabled:false,indicatorPersistence:persistence});
    const chart=useChartSurfaceRuntime();
    useLayoutEffect(()=>{runtime=indicators;surface=chart;});
    return <SingleChartPanes ref={chart.ref} seriesStore={reader} backendSyntheticSource={source}
      symbol={source.symbol} interval={source.interval} datasetKey={reader.seriesKey!} {...appearance}
      mainOverlayLines={indicators.view.mainOverlayLines} subPanes={indicators.view.subPanes}
      indicatorMarkers={indicators.view.markers} indicatorBgcolors={indicators.view.bgcolors}
      indicatorDrawings={indicators.view.drawings} indicatorBarcolors={indicators.view.barcolors}
      theme="dark" customBg="" upColor="#00aa00" downColor="#aa0000" drawingReadOnly />;
  }
  const render=()=>flushSync(()=>root.render(<MarketDataWorkspaceProvider><Probe/></MarketDataWorkspaceProvider>));
  const cases:unknown[]=[];
  async function check(kind:string) {
    const start=messages.length;render();
    const snapshot=()=>messages.slice(start).find(message=> {
      const definition=message.definition as { config?: { transform: string } } | undefined;
      return message.status==="ready"&&definition?.config?.transform===transform&&(message.complete===true||message.type==="snapshot");
    });
    await until(()=>Boolean(snapshot()),`${kind}/${transform}: snapshot missing`);
    const rows=snapshot()!.rows as Array<{close:number;time:number|{sourceTime:number}}>;
    const expected=rows.slice(1).map((row,index)=>(row.close+rows[index]!.close)/2);
    try { await until(()=>{
      const view=(runtime as IndicatorRuntime|null)?.view;
      if (!view || (runtime as IndicatorRuntime|null)?.status.computing) return false;
      const all=view.activeIndicators.flatMap(item=>item.error?[item.error]:[]);
      assert(!all.length,`${kind}/${transform}: ${all.join(",")}`);
      const ma=view.activeIndicators.find(item=>item.id==="ma")?.lines?.[0]?.data;
      const js=view.activeIndicators.find(item=>item.id==="js")?.lines?.[0]?.data;
      return JSON.stringify(ma?.map(point=>point.value))===JSON.stringify(expected)
        && JSON.stringify(js?.map(point=>point.value))===JSON.stringify(expected);
    },`${kind}/${transform}: indicator values did not match per-display-row MA`); }
    catch(error) { throw new Error(`${error}; expected=${JSON.stringify(expected)}; actual=${JSON.stringify((runtime as IndicatorRuntime|null)?.view.activeIndicators)}; computing=${(runtime as IndicatorRuntime|null)?.status.computing}`); }
    const clock=(runtime as IndicatorRuntime|null)!.view.activeIndicators.find(item=>item.id==="js")!.lines![1]!.data;
    assert(JSON.stringify(clock.map(point=>point.value))===JSON.stringify(rows.map(row=>typeof row.time==="number"?row.time:row.time.sourceTime)),"frontend JS received fake ordinal time");
    await until(()=>Boolean((surface as ReturnType<typeof useChartSurfaceRuntime>|null)?.actions.captureViewportTransfer()),"chart did not render");
    assert(!sockets.some(url=>url.includes("/indicators/")),"chart-derived indicator opened raw hosted stream");
    cases.push({kind,transform,points:expected.length});
  }
  try {
    for (const current of SYNTHETIC_TRANSFORMS) {transform=current;await check("CAPTURED_WINDOW");}
    // Parameter changes must invalidate the calculation even at identical source clocks.
    transform="renko";box=1;await check("PARAMETER_CHANGE");
    const capture=pinned.replay;
    const bind=(value:typeof capture)=>replaySyntheticSource({market,seriesKey:reader.seriesKey,
      sessionId:value.origin.session_id,trackId:value.origin.track_id,dataEpoch:value.origin.data_epoch,
      revealedBoundaryMs:value.origin.revealed_boundary_ms,sourceSequence:value.origin.source_sequence,
      ...(value.origin.history_epoch ? { historyEpoch:value.origin.history_epoch } : {})})!;
    reader.replace(capture.rows);source=bind(capture);transform="heikin-ashi";await check("REPLAY");
    const advanced=await(await fetch(`${API_BASE}/fixture/pinned/step`,{method:"POST"})).json() as Capture;
    reader.replace(advanced.rows);source=bind(advanced);await check("REPLAY_FORWARD");
    reader.replace(capture.rows);source=bind(capture);await check("REPLAY_REWIND");
    return {status:"PASS",cases,rawHostedSockets:0,realScriptClock:true,scope:"production browser hooks, DM snapshots, builtins and isolated frontend JS; native Pine verified separately"};
  } finally {flushSync(()=>root.unmount());host.remove();style.remove();window.WebSocket=Socket;}
}
