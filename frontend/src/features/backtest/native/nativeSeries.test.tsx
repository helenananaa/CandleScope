import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { NativeSeriesScene } from "./NativeSeriesScene.js";
import { nativeSeries } from "./nativeSeriesModel.js";
import { drawingColor } from "./nativeDrawingModel.js";
import type { NativeResult } from "./nativeBacktestApi.js";
const fixture=(language:string)=>JSON.parse(readFileSync(new URL(`./fixtures/${language}-series.json`,import.meta.url),"utf8")) as NativeResult;
for(const language of ["pine","pyne"]) test(`${language} actual installed output renders candles, markers, colors and fills`,()=>{
  const result=fixture(language), series=nativeSeries(result);
  for(const kind of ["line","candle","marker","background","barcolor","hline","fill"]) assert.ok(series.some(s=>s.kind===kind),kind);
  const markup=renderToStaticMarkup(<NativeSeriesScene result={result}/>);
  assert.match(markup,/data-series-kind="candle"/);
  assert.match(markup,/>X<\/text>/); assert.match(markup,/>UP<\/text>/);
  assert.ok(markup.indexOf('data-series-kind="background"')<markup.indexOf('data-series-kind="line"'));
  // Packed numeric Pine colors must never expand the price axis to billions.
  const heights=[...markup.matchAll(/<rect[^>]+height="([\d.]+)"/g)].map(m=>Number(m[1]));
  assert.ok(heights.some(h=>h>20 && h<40),'visible one-unit candle bodies on a seven-unit price range');
  if(language==="pine") {assert.match(markup,/<linearGradient/);assert.match(markup,/data-series-kind="bar"/);}
  assert.deepEqual(nativeSeries({...result,raw_output:{strategy_output:result.raw_output}}),series);
});
test("Pine RGB, RGBA and flagged low-RGB alpha retain actual colors",()=>{
  assert.equal(drawingColor(0x2196f3),'#2196f3');
  assert.equal(drawingColor(0x2196f34d),'#2196f34d');
  assert.equal(drawingColor(0x100000080),'#00000080');
  assert.equal(drawingColor('url(https://bad)'), '#38bdf8');
});
test("hidden plots, missing values, offsets and show_last do not expose future samples",()=>{
  const result=fixture('pine');
  result.raw_output={plots:[{id:1,values:[1,null,3,4,5],offset:1,showLast:2},{id:2,values:[1,2],display:'display.none'}],plotShapes:[{values:[false,0,null,true,false],locations:['location.abovebar']}]};
  const series=nativeSeries(result);
  assert.equal(series.length,2);assert.deepEqual(series[0]!.samples.map(p=>p.index),[4]);
  assert.deepEqual(series[1]!.samples.map(p=>p.index),[3]);
});
test("Pyne timestamps use actual chart bars and script text stays escaped",()=>{
  const result=fixture('pyne');
  result.raw_output={markers:[{data:[{time:result.bars[0]!.time,shape:'char',text:'<script>alert(1)</script>'},{time:1,shape:'char',text:'future'}]}]};
  assert.equal(nativeSeries(result)[0]!.samples.length,1);
  const html=renderToStaticMarkup(<NativeSeriesScene result={result}/>);
  assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);
});
test("absolute zero markers remain visible while missing and data-window-only markers do not",()=>{
  const result=fixture('pine');
  result.raw_output={plots:[],plotShapes:[{values:[0,null],locations:['location.absolute','location.absolute']},
    {values:[true],display:'display.data_window'}]};
  const series=nativeSeries(result);
  assert.equal(series.length,1);assert.deepEqual(series[0]!.samples.map(p=>p.index),[0]);
});
