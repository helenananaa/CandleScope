import type { NativeResult } from "./nativeBacktestApi.js";
import { drawingRows as rows, drawingNumber as number, drawingText as text, type DrawingRow } from "./nativeDrawingModel.js";

export interface SeriesSample extends DrawingRow { index: number }
export interface NativeSeries { kind: string; row: DrawingRow; samples: SeriesSample[]; pane: string }
const normalize = (row: DrawingRow): DrawingRow => Object.fromEntries(Object.entries(row).map(([k,v]) => [k.replaceAll("_", "").toLowerCase(),v]));
export function nativeSeries(result: NativeResult): NativeSeries[] {
  const raw = (result.raw_output.strategy_output ?? result.raw_output) as DrawingRow;
  const source=normalize(raw), series: NativeSeries[]=[];
  const families= ["plots","plotchars","plotshapes","plotarrows","plotbars","plotcandles","bgcolors","barcolors","hlines","fills"];
  const kindMap: Record<string,string>={plots:"line",plotchars:"marker",plotshapes:"marker",plotarrows:"marker",plotbars:"bar",plotcandles:"candle",bgcolors:"background",barcolors:"barcolor",hlines:"hline",fills:"fill"};
  const singular: Record<string,string>={values:"value",opens:"open",highs:"high",lows:"low",closes:"close",colors:"color",wickcolors:"wickcolor",bordercolors:"bordercolor",locations:"position",styles:"shape",chars:"char",texts:"text",textcolors:"textcolor",sizes:"size",colorups:"colorup",colordowns:"colordown",minheights:"minheight",maxheights:"maxheight"};
  for (const family of families) for (const item of rows(source[family])) {
    const row=normalize(item), kind=kindMap[family]!;
    const display=text(row.display);
    if (display.endsWith("none") || display.endsWith("data_window") || display.endsWith("status_line") || display.endsWith("price_scale")) continue;
    const pane=text(row.pane,"main");
    let arrowMaximum=0;
    if (family==="plotarrows") for (const value of Array.isArray(row.values)?row.values:[]) arrowMaximum=Math.max(arrowMaximum,Math.abs(number(value)??0));
    let samples: SeriesSample[]=[];
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
    if (kind==="marker") samples=samples.filter((s)=>(s.value!==null && s.value!==undefined &&
      (text(s.position).endsWith("absolute") ? number(s.value)!==undefined : s.value!==false && s.value!==0)));
    series.push({kind,row,samples,pane});
  }
  return series;
}
