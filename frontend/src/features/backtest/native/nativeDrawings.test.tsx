import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { NativeDrawingScene } from "./NativeDrawingScene.js";
import { nativeDrawings, drawingIndex, drawingColor, drawingCellSpan } from "./nativeDrawingModel.js";
import type { NativeResult } from "./nativeBacktestApi.js";

for (const language of ["pine","pyne"]) {
  test(`${language} installed runtime objects render all six object families`, () => {
    const result=JSON.parse(readFileSync(new URL(`../../../../tests/fixtures/native/${language}-drawings.json`,import.meta.url),"utf8")) as NativeResult;
    const scene=nativeDrawings(result);
    assert.equal(scene.objects.length,7);
    assert.deepEqual(new Set(scene.objects.map((o) => o.kind)),new Set(["lines","labels","boxes","polylines","linefills","tables"]));
    const html=renderToStaticMarkup(<NativeDrawingScene result={result} />);
    assert.match(html, /<polygon/);
    assert.match(html, /<path[^>]+ C/);
    assert.match(html, /colSpan="2"/i);
    assert.match(html, /Label &lt;b&gt;escaped&lt;\/b&gt;/);
    assert.doesNotMatch(html, /<b>escaped/);
    assert.match(html, /Merged title/);
    const external={...result,account_authority:"candlescope",raw_output:{strategy_output:result.raw_output}};
    assert.deepEqual(nativeDrawings(external),scene);
  });
}

test("Pine deletion and replay cutoffs select the last visible object state", () => {
  const result=JSON.parse(readFileSync(new URL('../../../../tests/fixtures/native/pine-drawings.json',import.meta.url),'utf8')) as NativeResult;
  result.raw_output.lines=[{id:1,snapshots:[{barIndex:0,exists:true,x1:0,y1:1,x2:1,y2:2},
    {barIndex:3,exists:false},{barIndex:10,exists:true,x1:0,y1:9,x2:1,y2:10}]}];
  assert.equal(nativeDrawings(result).objects.filter((o) => o.kind==='lines').length,0);
  result.bars=result.bars.slice(0,2);
  assert.equal(nativeDrawings(result).objects.filter((o) => o.kind==='lines').length,1);
});

test("timestamp coordinates honor engine units and chart gaps", () => {
  const bars=[0,60,180].map((time) => ({time,open:1,high:2,low:0,close:1}));
  assert.equal(drawingIndex(120000,'xloc.bar_time',bars,true),1.5);
  assert.equal(drawingIndex(120,'bar_time',bars,false),1.5);
  assert.equal(drawingIndex(2,'bar_index',bars,true),2);
  assert.equal(drawingColor('url(https://example.com/tracker)'),'#38bdf8');
});

test("merged cells hide covered cells and preserve span", () => {
  const merges=[{startrow:0,startcolumn:0,endrow:1,endcolumn:2}];
  assert.deepEqual(drawingCellSpan(0,0,merges),{hidden:false,rowSpan:2,colSpan:3});
  assert.equal(drawingCellSpan(1,2,merges).hidden,true);
  assert.equal(drawingCellSpan(2,2,merges).hidden,false);
});
