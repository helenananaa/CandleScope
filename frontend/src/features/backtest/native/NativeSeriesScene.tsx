import { useId, useMemo } from "react";
import { t } from "../../../i18n/index.js";
import type { NativeResult } from "./nativeBacktestApi.js";
import { nativeSeries } from "./nativeSeriesModel.js";
import { drawingColor as color, drawingNumber as num, drawingText as text, type DrawingRow } from "./nativeDrawingModel.js";

export function NativeSeriesScene({result}:{result:NativeResult}) {
  const scene=useMemo(()=>nativeSeries(result),[result]);
  const uid=useId().replaceAll(":","");
  if (!scene.length) return null;
  if (scene.reduce((n,s)=>n+s.samples.length,0)>100000) return <p role="status">{t("native.graphics.limit")}</p>;
  const panes=[...new Set(scene.map(s=>s.pane))];
  return <section aria-label={t("native.series.title")}><h3>{t("native.series.title")}</h3><p>{t("native.series.hint")}</p>{panes.map((pane,pi)=>{
    const layer: Record<string,number>={background:0,barcolor:1,fill:2,hline:3,line:4,candle:5,bar:6,marker:7};
    const series=scene.filter(s=>s.pane===pane).sort((a,b)=>(layer[a.kind]??9)-(layer[b.kind]??9)), bars=result.bars;
    const values=bars.flatMap(b=>[b.high,b.low]);
    for (const s of series.filter(s=>["line","hline","candle","bar","marker"].includes(s.kind))) for (const p of s.samples) for (const key of ["value","price","open","high","low","close"]) {
      if (s.kind==="marker" && !text(p.position).endsWith("absolute")) continue;
      const value=num(p[key]); if(value!==undefined) values.push(value);
    }
    let low=Infinity,high=-Infinity; for(const value of values) {low=Math.min(low,value);high=Math.max(high,value);}
    if (!Number.isFinite(low)) {low=0;high=1;}
    const span=high-low||1, width=920/Math.max(1,bars.length), x=(i:number)=>40+(i+.5)*width, y=(v:number)=>260-220*(v-low)/span;
    const paths=new Map(series.filter(s=>s.kind==="line" || s.kind==="hline").map(s=>[`${s.kind}:${text(s.row.id)}`,new Map(s.samples.map(p=>[p.index,num(p.value ?? p.price)]))]));
    const candle=(p:DrawingRow,i:number,col:unknown,bar=false)=>{
      const o=num(p.open),h=num(p.high),l=num(p.low),c=num(p.close);if(o===undefined||h===undefined||l===undefined||c===undefined)return null;
      const cx=x(i),w=Math.max(.5,Math.min(18,width*.65)),paint=color(col,c>=o?"#22c55e":"#ef4444");
      return <g><line x1={cx} x2={cx} y1={y(h)} y2={y(l)} stroke={color(p.wickcolor,paint)}/>{bar ? <path d={`M${cx-w/2},${y(o)}H${cx}V${y(c)}H${cx+w/2}`} fill="none" stroke={paint}/> :
        <rect x={cx-w/2} y={Math.min(y(o),y(c))} width={w} height={Math.max(1,Math.abs(y(o)-y(c)))} fill={paint} stroke={color(p.bordercolor,paint)}/>}</g>;
    };
    return <figure className="native-drawing-pane" key={pane}><figcaption>{pane}</figcaption><svg viewBox="0 0 1000 300" role="img" aria-label={`${t("native.series.title")} · ${pane}`}>
      {series.map((s,si)=><g key={si} data-series-kind={s.kind}><title>{text(s.row.title)}</title>{s.samples.map((p,i)=>{
        const cx=x(p.index), paint=color(p.color), bar=bars[p.index]!;
        if (s.kind==="background") return p.color==null ? null : <rect key={i} x={cx-width/2} y="15" width={width} height="270" fill={paint}/>;
        if (s.kind==="barcolor" && p.color==null) return null;
        if (s.kind==="candle" || s.kind==="bar" || s.kind==="barcolor") return <g key={i}>{candle(s.kind==="barcolor"?bar:p,p.index,p.color,s.kind==="bar")}</g>;
        if(s.kind==="hline") return i===0 && num(p.price)!==undefined ? <line key={i} x1="40" x2="960" y1={y(Number(p.price))} y2={y(Number(p.price))} stroke={paint} strokeDasharray="6 4"/>:null;
        if(s.kind==="line") {
          const next=s.samples[i+1], a=num(p.value),b=num(next?.value);
          return next && next.index===p.index+1 && a!==undefined && b!==undefined ? <line key={i} x1={cx} x2={x(next.index)} y1={y(a)} y2={y(b)} stroke={paint} strokeWidth={num(p.linewidth)??2}/>:null;
        }
        if(s.kind==="fill") {
          const first=paths.get(`${s.row.firstishline?"hline":"line"}:${text(s.row.firstid??s.row.plot1id)}`),second=paths.get(`${s.row.secondishline?"hline":"line"}:${text(s.row.secondid??s.row.plot2id)}`);
          const a=first?.get(p.index),b=second?.get(p.index);if(a===undefined||b===undefined)return null;
          const gradient=p.gradient as DrawingRow|undefined, id=`${uid}-${pi}-${si}-${i}`;
          const top=num(gradient?.topValue),bottom=num(gradient?.bottomValue);
          return <g key={i}>{gradient && top!==undefined && bottom!==undefined && <defs><linearGradient id={id} gradientUnits="userSpaceOnUse" x1={cx} x2={cx} y1={y(top)} y2={y(bottom)}><stop offset="0" stopColor={color(gradient.topColor,"transparent")}/><stop offset="1" stopColor={color(gradient.bottomColor,"transparent")}/></linearGradient></defs>}
            <rect x={cx-width/2} y={y(Math.max(a,b))} width={width} height={Math.abs(y(a)-y(b))} fill={gradient && top!==undefined && bottom!==undefined ? `url(#${id})`:color(p.color,"transparent")}/></g>;
        }
        if(s.kind!=="marker")return null;
        const position=text(p.position), shape=text(p.shape).replaceAll("_","").split(".").at(-1)??"circle";
        const below=position.includes("below"),cy=position.endsWith("absolute") ? y(num(p.value)??num(p.price)??bar.close):position.endsWith("top")?25:position.endsWith("bottom")?280:y(below?bar.low:bar.high)+(below?14:-14);
        const arrow=shape.includes("arrow"),up=shape.includes("up"),height=Math.max(5,Math.min(50,num(p.height)??15));
        return <g key={i} fill={paint} stroke={paint}>{shape==="char" ? <text x={cx} y={cy} textAnchor="middle" stroke="none">{text(p.char,p.text as string)}</text> : arrow ? <path d={`M${cx},${cy}v${up?-height:height}m-4,${up?4:-4}l4,${up?-4:4}l4,${up?4:-4}`} fill="none"/> : shape.includes("triangle") ? <polygon points={`${cx},${cy+(up?-5:5)} ${cx-5},${cy+(up?5:-5)} ${cx+5},${cy+(up?5:-5)}`}/> : shape==="square" ? <rect x={cx-4} y={cy-4} width="8" height="8"/> : shape==="diamond" ? <polygon points={`${cx},${cy-5} ${cx+5},${cy} ${cx},${cy+5} ${cx-5},${cy}`}/> : shape.includes("cross") ? <path d={`M${cx-4},${cy-4}l8,8m0,-8l-8,8`} fill="none"/> : <circle cx={cx} cy={cy} r="4"/>}
          {shape!=="char" && <text x={cx} y={cy+(below?15:-8)} textAnchor="middle" fill={color(p.textcolor,paint)} stroke="none" fontSize="10">{text(p.text)}</text>}</g>;
      })}</g>)}
    </svg></figure>;
  })}</section>;
}
