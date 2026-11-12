import assert from "node:assert/strict";
import test from "node:test";
import { chartIndicatorBars, chartIndicatorSelection, chartIndicatorSourceError } from "../chartIndicatorInput.js";
import { frontendScriptBars, parseFrontendScriptOutput } from "../frontendScriptRuntime.js";
import { EMPTY_SYNTHETIC } from "../../market-data/synthetic/syntheticSeries.js";
import { buildPaneDescriptors } from "../../../components/singleChartIndicatorPanes.js";
import { buildDisplaySourceTimeIndex, projectPaneDescriptorsToDisplay } from "../../chart-representation/derivedAuxiliaryProjection.js";
import { resolveChartPaneLegendValues } from "../../../components/chartPaneLegendModel.js";
import { alignIndicatorLinesToTimes } from "../../../chart-adapter/chartSeriesData.js";
import { buildMainSeriesData } from "../../../chart-adapter/mainSeriesModel.js";
import type { IndicatorComputeRequest, IndicatorLine } from "../indicatorTypes.js";

const rows = [102,104,106].map((close,ordinal) => ({ ordinal, id:`row-${ordinal}`,
  time: { order:ordinal, sourceTime:1700000040, sourceOrdinal:ordinal },
  open:close-2, high:close, low:close-2, close, volume:2,
  customValues: { chartProjection: { projectorId:"renko",sourceFromTime:1700000040,sourceToTime:1700000040,sourceOrdinal:ordinal,synthetic:true,provisional:ordinal>0 } } }));

test("ordered chart inputs preserve every brick and expose real script clocks", () => {
  const bars=chartIndicatorBars({ ...EMPTY_SYNTHETIC, status:"ready", rows },true);
  assert.deepEqual(bars.map(row=>row.time),[1,2,3]);
  assert.deepEqual(bars.map(row=>row.is_closed),[true,false,false]);
  const request:IndicatorComputeRequest={script:'plot("x", bars.map(b=>b.close))',ohlcv:bars.map(row=>({
    time:Number(row.time),sourceTime:Number(row.sourceTime),open:Number(row.open),high:Number(row.high),low:Number(row.low),close:Number(row.close),volume:row.volume??0 }))};
  assert.deepEqual(frontendScriptBars(request).map(row=>row.time),[1700000040,1700000040,1700000040]);
  const result=parseFrontendScriptOutput(JSON.stringify({lines:[{name:"x",pane:"main",color:"#abcdef",values:[102,104,106]}]}),request);
  assert.deepEqual(result.lines[0]!.data.map(row=>row.time),[1,2,3]);
  assert.deepEqual(chartIndicatorSelection(null,null,{chartType:"heikin-ashi",renkoBoxSize:10}).settings,{});
});

test("chart lines bypass raw-time filtering and map to each exact brick; market panes retain their source axis", () => {
  const line:IndicatorLine={id:"ma",inputAxis:"display-ordinal",data:[{time:2,value:103},{time:3,value:105}]};
  const market:IndicatorLine={id:"funding",data:[{time:1700000040,value:7}]};
  const panes=buildPaneDescriptors({dataTimeSet:new Set([1700000040]),intervalSeconds:60,mainOverlayLines:[line,market],
    paneOrder:["main"],subPanes:[],indicatorMarkers:[],indicatorFills:[],indicatorHlines:[],indicatorBgcolors:[]});
  assert.equal(panes[0]!.lines[0]!.data!.length,2);
  const display=projectPaneDescriptorsToDisplay(panes,buildDisplaySourceTimeIndex(rows));
  assert.deepEqual(display[0]!.lines[0]!.data,[{time:rows[1]!.time,value:103},{time:rows[2]!.time,value:105}]);
  assert.equal(display[0]!.lines[1]!.data!.length,3);
  assert.deepEqual(resolveChartPaneLegendValues([line],rows[1]!.time).map(row=>row.value),[103]);
  assert.deepEqual(resolveChartPaneLegendValues([line],rows[2]!.time).map(row=>row.value),[105]);
  const main=buildMainSeriesData(rows,{indicatorBarcolors:[{inputAxis:"display-ordinal",data:[{time:2,color:"red"}]}]});
  assert.equal(main[1]!.color,"red");
  assert.notEqual(main[0]!.color,"red");
  const colored=alignIndicatorLinesToTimes([{...line,type:"histogram",colorData:[{time:2,color:"purple"}]}],new Set([1700000040]));
  assert.equal(colored[0]!.data![0]!.color,"purple");
});


test("an unavailable chart input is explicit and never reports readiness or raw-bar fallback", () => {
  assert.equal(chartIndicatorSourceError({ ...EMPTY_SYNTHETIC, status:"unavailable", reason:"captured input expired" },"unavailable"),"captured input expired");
  assert.equal(chartIndicatorSourceError(EMPTY_SYNTHETIC,"capture registration failed"),"capture registration failed");
  assert.equal(chartIndicatorSourceError(EMPTY_SYNTHETIC,"preparing"),null);
});
