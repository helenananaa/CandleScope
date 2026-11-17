import fs from 'node:fs/promises';
import { createDefaultChartWorkspaceRecord } from '../../../frontend/src/features/chart-workspace/chartWorkspaceLibrary.ts';
import { applyControlWorkspaceCommand } from '../../../frontend/src/features/chart-workspace/chartWorkspaceControl.ts';
import { parseControlConfiguration } from '../../../frontend/src/features/app-control/controlModel.ts';
import { normalizeChartWorkspaceWithDiagnostics } from '../../../frontend/src/features/chart-workspace/chartWorkspaceStorage.ts';
import { CHART_WORKSPACE_BOOTSTRAP_KEY, CHART_WORKSPACE_ACTIVE_ID_KEY } from '../../../frontend/src/features/chart-workspace/chartWorkspaceRepository.ts';
const record=createDefaultChartWorkspaceRecord(0);
const command=parseControlConfiguration({requestId:'qa463-initial-ui',workspaceId:record.id,windowId:'main-window',
  expectedRevision:record.document.revision,layout:'quad',charts:['89m','97m','101m','10007m'].map(interval=>({
    session:{exchange:'binance',marketType:'futures',symbol:'BTCUSDT',interval},indicators:[{name:'EMA',period:20},{name:'EMA',period:60}]}))});
record.document=applyControlWorkspaceCommand(record.document,command,{}).document;
for(const [index,cell] of Object.values(record.document.cells).entries()) cell.indicators.push({
  id:'joint-close-'+(index+1),name:'Joint native close input',kind:'script',executionTarget:'local',language:'frontend-js',securityMode:'safe',
  script:'plot("close",bars.map(bar=>bar.close),{pane:"main",color:"#f59e0b"});',params:{},visible:true});
const normalized=normalizeChartWorkspaceWithDiagnostics(record.document);
if(normalized.usedFallback || normalized.diagnostics.length) throw Error(JSON.stringify(normalized.diagnostics));
await fs.writeFile(process.argv[2],JSON.stringify({scope:'UI preferences only; no candles, indicator results, replay or market seeds',
  storage:{[CHART_WORKSPACE_BOOTSTRAP_KEY]:JSON.stringify(record),[CHART_WORKSPACE_ACTIVE_ID_KEY]:record.id}},null,2)+'\n');
