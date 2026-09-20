import type { NativeResult } from "./nativeBacktestApi.js";
import { drawingRows as rows, drawingNumber as number, drawingText as text, type DrawingRow } from "./nativeDrawingModel.js";

export interface SeriesSample extends DrawingRow { index: number }
export interface NativeSeries { kind: string; row: DrawingRow; samples: SeriesSample[]; pane: string }
const normalize = (row: DrawingRow): DrawingRow => Object.fromEntries(Object.entries(row).map(([k,v]) => [k.replaceAll("_", "").toLowerCase(),v]));
export function nativeSeries(result: NativeResult): NativeSeries[] {
  const raw = (result.raw_output.strategy_output ?? result.raw_output) as DrawingRow;
  const pine = Array.isArray(raw.plots);
  const source=normalize(raw), series: NativeSeries[]=[];
  const indices=new Map(result.bars.map((bar,i) => [bar.time,i]));
  const families=pine ? ["plots","plotchars","plotshapes","plotarrows","plotbars","plotcandles","bgcolors","barcolors","hlines","fills"] :
    ["lines","markers","candles","bgcolors","barcolors","hlines","fills"];
  const kindMap: Record<string,string>={plots:"line",lines:"line",plotchars:"marker",plotshapes:"marker",plotarrows:"marker",markers:"marker",plotbars:"bar",plotcandles:"candle",candles:"candle",bgcolors:"background",barcolors:"barcolor",hlines:"hline",fills:"fill"};
  const singular: Record<string,string>={values:"value",opens:"open",highs:"high",lows:"low",closes:"close",colors:"color",wickcolors:"wickcolor",bordercolors:"bordercolor",locations:"position",styles:"shape",chars:"char",texts:"text",textcolors:"textcolor",sizes:"size",colorups:"colorup",colordowns:"colordown",minheights:"minheight",maxheights:"maxheight"};
  for (const family of families) for (const item of rows(source[family])) {
    const row=normalize(item), kind=kindMap[family]!;
    const display=text(row.display);
    if (display.endsWith("none") || display.endsWith("data_window") || display.endsWith("status_line") || display.endsWith("price_scale")) continue;
    const pane=text(row.pane,"main");
    let arrowMaximum=0;
    if (family==="plotarrows") for (const value of Array.isArray(row.values)?row.values:[]) arrowMaximum=Math.max(arrowMaximum,Math.abs(number(value)??0));
    let samples: SeriesSample[]=[];
    if (pine) {
      samples=result.bars.map((_,i) => {
        const sample: SeriesSample={...row,index:i+(number(row.offset) ?? 0)};
        for (const [key,value] of Object.entries(row)) if (Array.isArray(value)) sample[singular[key] ?? key]=value[i];
        if (family==="bgcolors" || family==="barcolors") sample.color=sample.value;
        if (family==="plotchars") sample.shape="char";
        if (family==="plotarrows") {
          const up=(number(sample.value) ?? 0)>0;
          sample.shape=up ? "arrow_up":"arrow_down";
          sample.position=up ? "below":"above"; sample.color=up ? sample.colorup:sample.colordown;
          const minimum=number(sample.minheight)||5, maximum=number(sample.maxheight)||30;
          sample.height=minimum+(maximum-minimum)*Math.abs(number(sample.value)??0)/(arrowMaximum||1);
        }
        return sample;
      }).filter((s,i) => i >= result.bars.length-(number(row.showlast) ?? result.bars.length) && s.index>=0 && s.index<result.bars.length);
    } else {
      samples=rows(row.data ?? row.regions).map((value) => ({...row,...normalize(value),index:indices.get(Number(value.time)) ?? -1})).filter((s)=>s.index>=0);
      if (["fill","hline"].includes(kind)) samples=result.bars.map((_,index)=>({...row,index}));
    }
    if (kind==="marker") samples=samples.filter((s)=>!pine || (s.value!==null && s.value!==undefined &&
      (text(s.position).endsWith("absolute") ? number(s.value)!==undefined : s.value!==false && s.value!==0)));
    series.push({kind,row,samples,pane});
  }
  return series;
}
