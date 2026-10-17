import { act, useLayoutEffect, useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";
import SingleChartPanes from "../../components/SingleChartPanes.js";
import { useChartSurfaceRuntime, type ChartSurfaceVisibleRange } from "../useChartSurfaceRuntime.js";
import { SeriesWindowStore } from "../../features/market-data/window/seriesWindowStore.js";
import type { KlineBar } from "../../features/market-data/marketDataTypes.js";

/** Live initialization does not opt into replay's followLatest lifecycle. */
export async function checkLiveSyntheticSession() {
  const samples: unknown[] = [];
  const rows: KlineBar[] = Array.from({length: 1501}, (_, i) => {
    const open = 110 + Math.sin(i * .13), close = open + Math.sin(i * .41) * .12;
    return {time: (1_800_000_000 + i * 300) as KlineBar["time"], open, close,
      high: Math.max(open,close)+.1, low: Math.min(open,close)-.1, volume:10};
  });
  for (const auxiliary of [true, false]) {
    const host=document.createElement("div"),style=document.createElement("style");
    host.className="qa-live-session";host.style.cssText="width:700px;height:400px;position:relative;display:flex";
    style.textContent=".qa-live-session .chart-area{position:relative;flex:1;height:100%;min-width:0}.qa-live-session .chart-pane{position:absolute;inset:0}.qa-live-session .pane-overlay-anchor{position:absolute;left:10px}";
    document.head.append(style);document.body.append(host);
    const scope=`qa-live-session-${auxiliary}-${crypto.randomUUID()}`;
    const store=new SeriesWindowStore({seriesKey:scope});store.replace(rows.slice(950));
    let root=createRoot(host);let surface:ReturnType<typeof useChartSurfaceRuntime>|null=null;
    let saved:ChartSurfaceVisibleRange={barSpacing:8,rightOffset:4};let phase="memory-cache-hit";
    let initial=saved;
    function Probe(){
      const value=useChartSurfaceRuntime();const source=useSyncExternalStore(listener=>store.subscribe(()=>listener()),()=>store.snapshot());
      useLayoutEffect(()=>{surface=value;});
      return <SingleChartPanes ref={value.ref} seriesStore={store} datasetKey={scope}
        dataMeta={{seriesKey:scope,version:store.version,status:"ready",source:phase,committedAt:null}}
        symbol="BTCUSDT" interval="5m" chartType="renko" theme="dark" customBg=""
        upColor="#00aa00" downColor="#aa0000" drawingReadOnly followLatest={false}
        savedVisibleRange={initial} onVisibleRangeChange={range=>{saved=range;}}
        subPanes={auxiliary?[{id:"rsi",label:"Oscillator",lines:[{id:"rsi",pane:"separate",name:"Oscillator",color:"#a855f7",data:source.map(row=>({time:Number(row.time),value:50+Math.sin(Number(row.time)/300)*10}))}]}]:[]}/>;
    }
    const settle=async()=>{for(let i=0;i<8;i++)await act(async()=>{await new Promise(requestAnimationFrame);});};
    const handle=()=> (surface as ReturnType<typeof useChartSurfaceRuntime>|null)!.actions;
    const view=()=>handle().getVisibleRange();
    const assertTail=(stage:string)=>{
      const current=view();
      if(!current?.logical || Math.abs((current.rightOffset ?? Infinity)-4)>1e-5
        || Math.abs((current.barSpacing ?? 0)-8)>.3) {
        throw new Error(`${auxiliary} ${stage}: ${JSON.stringify(current)}`);
      }
      samples.push({auxiliary,stage,view:current});
    };
    try {
      await act(async()=>root.render(<Probe/>));await settle();assertTail(phase);
      phase="initial-history";await act(async()=>{store.replace(rows);});await settle();assertTail(phase);
      for(let n=0;n<5;n++){
        const last=rows.at(-1)!;await act(async()=>{store.applyTick({...last,close:Number(last.close)+(n%2?-.5:.8),high:Number(last.high)+1,low:Number(last.low)-1});});
        await settle();assertTail(`tick ${n}`);
      }
      // Full surface remount consumes the settled persisted semantic offset.
      saved=handle().getVisibleRange()!;
      await act(async()=>root.unmount());
      initial=saved;root=createRoot(host);
      await act(async()=>root.render(<Probe/>));await settle();assertTail("reopen");
      // Linked/user navigation takes ownership; later ticks must not snap back
      // to the automatic startup tail.
      const requested={from:Number(rows[800]!.time),to:Number(rows[1000]!.time)};
      if(!handle().setLinkedVisibleTimeRange(requested))throw new Error("linked navigation rejected");
      await settle();const before=view();
      await act(async()=>store.applyTick({...rows.at(-1)!,close:109.6,high:112,low:108}));
      await settle();const after=view();
      if(!before?.time || !after?.time || Math.abs(after.time.from-before.time.from)>.01
        || Math.abs(after.time.to-before.time.to)>.01)throw new Error(`linked view lost: ${JSON.stringify({before,after})}`);
      samples.push({auxiliary,stage:"linked ownership through tick",before,after});
    } finally {await act(async()=>root.unmount());host.remove();style.remove();}
  }
  return {name:"live synthetic session initialization and ticks",status:"PASS",samples};
}
