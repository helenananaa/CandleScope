import { useLayoutEffect } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import { API_BASE } from "../../services/apiConfig.js";
import { useIndicatorRuntime } from "../../features/indicators/useIndicatorRuntime.js";
import { createActiveIndicatorPersistence } from "../../features/indicators/activeIndicatorStore.js";
import type { IndicatorRuntime } from "../../features/indicators/indicatorRuntimeContract.js";
import type { KlineBar } from "../../features/market-data/marketDataTypes.js";
import { SeriesWindowStore } from "../../features/market-data/window/seriesWindowStore.js";
import SingleChartPanes from "../../components/SingleChartPanes.js";

function assert(value:unknown,message:string):asserts value { if(!value)throw Error(message); }
const delay=(ms:number)=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(predicate:()=>boolean,message:string) {
  const deadline=performance.now()+12000;
  while(!predicate()){assert(performance.now()<deadline,message);await delay(20);}
}

/** Real React hook, chart renderer, HTTP/WS and Pine service. Only BAR/feed production is controlled. */
export async function checkChartCalculation() {
  const originalFetch=window.fetch.bind(window),NativeSocket=window.WebSocket;
  const http:Array<Record<string,unknown>>=[],frames:Array<Record<string,unknown>>=[];
  let hold=false,held=false,release:()=>void=()=>{};
  window.fetch=async(input,options)=>{
    const response=await originalFetch(input,options);
    const url=String(input);
    if(url.includes("/indicators/calculations")) {
      const payload=await response.clone().json() as Record<string,unknown>;
      http.push({url,method:options?.method,calculation:payload.calculation,type:payload.type,code:payload.code,ok:payload.ok,error:payload.error});
      if(hold && url.endsWith("/range")){
        hold=false;held=true;await new Promise<void>(yes=>{release=yes;});
      }
    }
    return response;
  };
  class ObservedSocket extends NativeSocket {
    constructor(url:string|URL,protocols?:string|string[]){
      super(url,protocols);this.addEventListener("message",event=>{frames.push(JSON.parse(String(event.data)) as Record<string,unknown>);});
    }
  }
  window.WebSocket=ObservedSocket;
  const storage=new Map<string,string>(),persistence=createActiveIndicatorPersistence("chart-domain",{
    getItem:key=>storage.get(key)??null,setItem:(key,value)=>{storage.set(key,value);},
  });
  const readBars=async()=>await(await originalFetch(`${API_BASE}/fixture/bars`)).json() as {rows:KlineBar[];script:string};
  let data=await readBars(),rows=data.rows,revision=1;
  const latest=new Map<string,IndicatorRuntime>();
  const script=data.script.replace("varip int ticks",'qa = input.int(1, "QA")\nvarip int ticks');
  persistence.save([{id:"counter",language:"pine",kind:"script",name:"owned counter",script,visible:true}]);
  const host=document.createElement("div");host.style.cssText="width:900px;height:600px;display:flex;position:relative";document.body.append(host);
  const style=document.createElement("style");style.textContent=".chart-area{position:relative;flex:1;height:100%;min-width:0}.chart-pane{position:absolute;inset:0}";document.head.append(style);
  const root=createRoot(host),store=new SeriesWindowStore({intervalSeconds:60});
  const otherHost=document.createElement("div");otherHost.style.cssText=host.style.cssText;document.body.append(otherHost);
  const otherRoot=createRoot(otherHost);
  function Cell({owner="left"}:{owner?:string}){
    const runtime=useIndicatorRuntime({chartData:rows,chartDataMeta:{version:revision,status:"ready",committedAt:1,source:"controlled BAR"},
      exchange:"binance",marketType:"spot",symbol:"BTCUSDT",interval:"1m",datasetKey:"owned",sessionKey:"owned",
      autoAddVolume:false,indicatorPersistence:persistence});
    useLayoutEffect(()=>{latest.set(owner,runtime);});
    return <SingleChartPanes symbol="BTCUSDT" interval="1m" datasetKey="owned" seriesStore={store}
      theme="dark" customBg="" upColor="#00aa00" downColor="#aa0000" drawingReadOnly followLatest={false}
      mainOverlayLines={runtime.view.mainOverlayLines} subPanes={runtime.view.subPanes}
      indicatorMarkers={runtime.view.markers} indicatorBgcolors={runtime.view.bgcolors}
      indicatorFills={runtime.view.fills} indicatorHlines={runtime.view.hlines} indicatorDrawings={runtime.view.drawings}/>;
  }
  const render=()=>{store.replace(rows);flushSync(()=>root.render(<Cell/>));};
  const runtime=(owner="left")=>{const result=latest.get(owner);assert(result,"runtime missing");return result;};
  const value=(owner="left")=>runtime(owner).view.activeIndicators[0]?.lines?.find(line=>line.name==="counter")?.data.at(-1)?.value;
  const post=async(path:string)=>await originalFetch(`${API_BASE}/fixture/${path}`,{method:"POST"});
  const state=async()=>await(await originalFetch(`${API_BASE}/fixture/state`)).json() as {registry:{entries:number};callbacks:number;leases:number};
  const at=(value:unknown,time:number):boolean=>Array.isArray(value)?value.some(item=>at(item,time)):
    value!==null&&typeof value==="object"?("time" in value&&Number(value.time)===time)||Object.values(value).some(item=>at(item,time)):false;
  const observations:Array<Record<string,unknown>>=[];
  const record=(stage:string)=>{observations.push({stage,counter:value(),right:latest.has("right")?value("right"):null,
    markers:runtime().view.markers.map(marker=>({id:marker.id,data:marker.data?.filter(point=>Number(point.time)>=Number(rows.at(-4)!.time))})),
    bgcolors:runtime().view.bgcolors.map(item=>({id:item.id,data:item.data?.filter(point=>Number(point.time)>=Number(rows.at(-4)!.time))}))});};
  try {
    render();await until(()=>value()===500,"initial 500-bar owned counter missing");
    await until(()=>frames.some(frame=>frame.type==="indicator.subscribed"&&frame.ok===true),"owned WS did not attach");record("initial500");
    assert(http.filter(item=>item.method==="POST"&&String(item.url).endsWith("/calculations")).length===1,"initial open was duplicated");
    await post("tick/501");await until(()=>value()===501,"500 to501 regressed");record("first501");
    data=await readBars();rows=data.rows;revision++;render();
    await post("tick/501?close=103");await until(()=>value()===502,"forming observation502 missing");record("second502");
    const shifted=Number(rows.at(-3)!.time);
    assert(at(runtime().view.markers,shifted)&&at(runtime().view.bgcolors,shifted),"negative-offset marker/bgcolor missing");
    await post("tick/501?close=104");await until(()=>value()===503,"forming observation503 missing");record("third503");
    assert(!at(runtime().view.markers,shifted)&&!at(runtime().view.bgcolors,shifted),"negative-offset deletion was merged as append");
    assert(!at(runtime().view.activeIndicators[0]?.lines?.filter(line=>line.name==="old point"),shifted),"negative-offset plot was not deleted");
    flushSync(()=>otherRoot.render(<Cell owner="right"/>));
    await until(()=>value("right")===500,"independent chart did not seed its own opaque history");
    await until(()=>frames.filter(frame=>frame.type==="indicator.subscribed"&&frame.ok===true).length>=2,"second domain WS did not attach");
    await delay(100);assert(value()===503,"second chart's500 replaced first chart's503 through shared cache");
    observations.push({stage:"independent-charts",left:value(),right:value("right")});
    await post("amend");await until(()=>value()===501,"source generation did not replace the full cumulative projection");record("amend-generation2");
    assert(frames.some(frame=>frame.calculation&&Number((frame.calculation as Record<string,unknown>).generation)===2),"new source generation absent");
    // Hold a genuine old-domain HTTP response until a different definition has
    // opened and rendered. The response and all mathematics remain unmodified.
    hold=true;
    assert(runtime().actions.requestIndicatorRange(Number(rows[0]!.time),Number(rows.at(-2)!.time),"qa-held-response",{
      invalidate:true,waitForSubscription:false,
    }),"held range not admitted");
    await until(()=>held,"real old-domain range was not dispatched");
    const parameter=runtime().view.activeIndicators[0]?.paramSchema?.[0];
    const key=parameter?.key||parameter?.name;assert(key,"actual Pine input schema missing");
    flushSync(()=>runtime().actions.updateIndicatorParams("counter",{[key]:2}));
    await until(()=>http.filter(item=>item.method==="POST"&&String(item.url).endsWith("/calculations")).length===3&&value()===500,
      "changed definition did not replace its domain");
    release();await delay(150);assert(value("right")===500,"new left definition changed the right projection");assert(value()===500,"late old-domain response overwrote new math");record("new-definition500");
    assert(host.querySelectorAll("canvas").length>0,"real chart renderer missing");
    return {scope:"Real React/SingleChartPanes + HTTP/WS + Manager/SQLite/repository SDK/Pine core; controlled feeds, not Native/package",observations,http,
      frames:frames.map(frame=>({type:frame.type,calculation:frame.calculation,code:frame.code})),state:await state()};
  } catch(error) {
    throw new Error(String(error)+" observations="+JSON.stringify({observations,http:http.slice(-8),error:runtime().view.activeIndicators[0]?.error}));
  } finally {
    release();flushSync(()=>{root.unmount();otherRoot.unmount();});
    const opened=new Set(http.filter(item=>item.ok===true&&item.method==="POST"&&String(item.url).endsWith("/calculations"))
      .map(item=>(item.calculation as Record<string,unknown>).domainId)).size;
    await until(()=>http.filter(item=>item.method==="DELETE").length>=opened,"owned domains not released on definition change/unmount");
    const final=await state();assert(final.registry.entries===0&&final.callbacks===0&&final.leases===0,"chart cleanup leaked owners or source inputs");
    host.remove();otherHost.remove();style.remove();window.fetch=originalFetch;window.WebSocket=NativeSocket;
  }
}
