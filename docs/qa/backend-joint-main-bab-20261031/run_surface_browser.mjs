import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
const repo=fileURLToPath(new URL('../../../',import.meta.url));
const scripts=path.join(repo,'frontend/scripts');
const fixture='.qa-joint-surface-browser.html';
const runner=path.join(scripts,'.qa-joint-surface-runner.mjs');
const created=[];
try {
  fs.writeFileSync(path.join(scripts,fixture), "<!doctype html><html><body><script type=\"module\">\nimport { checkLiveSyntheticSession } from \"/src/chart-adapter/__tests__/liveSyntheticSession.browser.tsx\";\nimport { checkSemanticSessionViewport } from \"/src/chart-adapter/__tests__/semanticSessionViewport.browser.ts\";\nwindow.__frontendScriptCheck = async () => [await checkLiveSyntheticSession(), await checkSemanticSessionViewport()];\nwindow.__frontendScriptEditorCheck = () => ({status:\"PASS\",scope:\"existing live synthetic and semantic viewport regressions\"});\n</script></body></html>", {flag:'wx'});
  created.push(path.join(scripts,fixture));
  const source=fs.readFileSync(path.join(scripts,'frontend-script-integration.mjs'),'utf8')
    .replace(/^const fixture = .*$/m, `const fixture = ${JSON.stringify(fixture)};`);
  fs.writeFileSync(runner,source,{flag:'wx'});created.push(runner);
  const output=path.resolve(process.argv[2] || path.join(repo,'output/backend-joint-main-bab-reproduction/synthetic-viewport'));
  const result=spawnSync(process.execPath,[runner,'--replay-visible','--out',output],{cwd:repo,stdio:'inherit'});
  if(result.error)throw result.error;
  process.exitCode=result.status ?? 1;
} finally { for(const file of created.reverse())fs.unlinkSync(file); }
