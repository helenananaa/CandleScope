import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';
const out=process.env.CANDLESCOPE_RESEARCH_ISOLATION_OUT;
assert.ok(out&&!fs.existsSync(out),'Use a fresh evidence directory');fs.mkdirSync(out,{recursive:true});
const {chromium}=createRequire(process.env.CANDLESCOPE_PLAYWRIGHT_PACKAGE)('playwright-core');
const browser=await chromium.launch({channel:'chrome',headless:true}),receipt={scope:'Actual production chart/research editor components, registry and draft persistence in browser fixture. No API substitution, market data, strategy engine or native qualification.',steps:[],errors:[],apiMutations:[]};
let currentPage;
const save=()=>fs.writeFileSync(out+'/receipt.json',JSON.stringify(receipt,null,2)+'\n');
try{
 for(const language of ['pine','python'])for(const entry of ['menu','command']){
  const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();currentPage=page;
  page.on('pageerror',error=>receipt.errors.push(String(error.stack||error)));
  page.on('request',request=>{if(request.method()!=='GET'&&new URL(request.url()).pathname.startsWith('/api/'))receipt.apiMutations.push(request.url());});
  await page.goto('http://127.0.0.1:23182/tests/fixtures/research-isolation/entry.html?language='+language);
  const group='host-chart-strategy:isolation',research='host-strategy:experiment';
  const ready=async id=>page.waitForFunction(id=>window.researchIsolationQA?.registry.list().find(g=>g.id===id)?.commands.some(c=>c.name==='source'&&c.available),id);
  async function command(id,name,args={}){
   const response=await page.evaluate(async({id,name,args})=>{
    const registry=window.researchIsolationQA.registry,group=registry.list().find(g=>g.id===id),requestId=crypto.randomUUID();
    return registry.execute({id:requestId,method:'app.execute',params:{windowId:'main-window',groupId:id,command:name,args,requestId,expectedContext:group.contextToken}},'main-window');
   },{id,name,args});assert.equal(response.state,'applied',JSON.stringify(response));return response;
  }
  await ready(group);await page.locator('[data-chart-strategy-panel] .monaco-editor').waitFor();
  const before=await page.evaluate(()=>window.researchIsolationQA.inspect());
  const clicked=before.original.source+(language==='python'?'\n# clicked unsaved code':'\n// clicked unsaved code');
  await command(group,'source',{source:clicked});
  if(entry==='command')await command(group,'openWorkspace');
  else{
   const labels=await page.evaluate(()=>window.researchIsolationQA.labels);
   await page.getByLabel(labels.more,{exact:true}).click();await page.getByRole('menuitem',{name:labels.open,exact:true}).click();
  }
  await ready(research);
  const fork=await page.evaluate(()=>window.researchIsolationQA.inspect());
  assert.ok(fork.handoff);assert.notEqual(fork.handoff.draftId,before.original.id);
  assert.equal(fork.original.source,clicked);assert.equal(fork.experiment.source,clicked);
  assert.ok(fork.handoff.origin.draftRevision<=fork.original.revision);
  // The chart Monaco can publish its own initial cursor after source restore.
  // Let that existing 550ms autosave drain before isolating research edits.
  await page.waitForTimeout(650);
  const originBeforeResearch=(await page.evaluate(()=>window.researchIsolationQA.inspect())).original;
  assert.equal(originBeforeResearch.source,clicked);
  const edited=clicked+(language==='python'?'\n# independent experiment':'\n// independent experiment');
  await command(research,'pane',{pane:'code'});
  const editor=page.locator('[data-testid="strategy-research-script-panel"] .monaco-editor [role="textbox"]');
  await editor.focus();await page.keyboard.press('Meta+A');await page.keyboard.insertText(edited);
  await page.waitForFunction(source=>window.researchIsolationQA.registry.list().find(g=>g.id==='host-strategy:experiment')?.context.source===source,edited);
  await command(research,'flush');
  const after=await page.evaluate(()=>window.researchIsolationQA.inspect());
  assert.deepEqual(after.original,originBeforeResearch);assert.equal(after.experiment.source,edited);
  await page.reload();await ready(group);await ready(research);await command(research,'pane',{pane:'code'});
  await page.locator('[data-testid="strategy-research-script-panel"] .monaco-editor').waitFor();
  const restored=await page.evaluate(()=>window.researchIsolationQA.inspect());
  assert.deepEqual(restored.original,originBeforeResearch);assert.equal(restored.experiment.source,edited);
  assert.equal(restored.handoff.draftId,fork.handoff.draftId);
  await page.waitForFunction(()=>{const e=document.querySelector('[data-testid="strategy-research-script-panel"] .monaco-editor');return e?.getBoundingClientRect().height>200&&/independent\s+experiment/.test(e.textContent);});
  await page.screenshot({path:out+'/'+language+'-'+entry+'.png',fullPage:true});
  receipt.steps.push({name:language+'-'+entry,originId:fork.original.id,originRevision:fork.original.revision,
   experimentId:fork.experiment.id,originalPreserved:true,clickedSourceCopied:true,researchEditsIndependent:true,reloadRestoresBoth:true});save();await context.close();
 }
 assert.deepEqual(receipt.errors,[]);assert.deepEqual(receipt.apiMutations,[]);receipt.passed=true;
}catch(error){receipt.failure=String(error.stack||error);process.exitCode=1;
 if(currentPage&&!currentPage.isClosed()){
  receipt.failureInputs=await currentPage.locator('.monaco-editor').evaluateAll(elements=>elements.map(e=>[...e.querySelectorAll('[contenteditable],textarea,input,[role="textbox"]')].map(x=>({tag:x.tagName,class:x.className,role:x.getAttribute('role'),aria:x.getAttribute('aria-label')}))));
  await currentPage.screenshot({path:out+'/failure.png',fullPage:true,timeout:5000}).catch(()=>{});
 }}
finally{await browser.close();save();console.log(JSON.stringify({passed:receipt.passed??false,steps:receipt.steps.length,failure:receipt.failure}));}
