import os,json,gzip,subprocess,datetime,concurrent.futures,re,hashlib
from pathlib import Path
R=Path('/Users/ryanliang/.codex/worktrees/chart-strategy-sessions-20261104/CandleScope');O=Path('/Users/ryanliang/CandleScope/output/development-goal-20261104/continuous-stack-main266-20261106')
def git(*a):return subprocess.check_output(['git',*a],cwd=R,text=True).strip()
source=git('rev-parse','HEAD');assert source=='e7821d763c4faa97f38722acc6bae1a78043b006' and not git('status','--porcelain')
old=json.loads(gzip.decompress((R/'docs/qa/research-selected-version-20261105/main261-20261106/source-manifest.json.gz').read_bytes()))
suites=[x for x in old['command'] if x.startswith('backend/tests/')];suites=list(dict.fromkeys(suites+json.loads(gzip.decompress((R/'docs/qa/replay-imported-multimarket-20261106/evidence/backend-combined-files.json.gz').read_bytes()))))
t=Path('/tmp/candlescope-continuous-main266-20261106/full-top');t.mkdir(parents=True,exist_ok=False);(t/'data').mkdir()
env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':'packages/candlescope-plugin-sdk/src:packages/candlescope-backtest-sdk/src:backend','DATA_DIR':str(t/'data'),'CANDLE_DATA_DIR':str(t/'data'),'NATIVE_TEST_PINE_PYTHON':str(O/'pine/python')}
commands={'backend':[old['command'][0],'-B','-m','pytest',*suites,'--basetemp='+str(t/'pytest'),'-q','-rs'],'frontend':['npm','run','check']}
report={'source':source,'main':'7acba72e56dfafd3a25ee4ec861509f4e9dc6f96','commands':commands,'backendSuites':suites,'env':{k:env[k] for k in ['PYTHONDONTWRITEBYTECODE','PYTHONPATH','DATA_DIR','CANDLE_DATA_DIR','NATIVE_TEST_PINE_PYTHON']},'sourceOnlyPineRunner':True,'nativeQualified':False,'startedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'results':{}}
(O/'full-checks.json').write_text(json.dumps(report,indent=2)+'\n')
def run(name):
 with (O/(name+'-full.log')).open('w') as f:
  p=subprocess.run(commands[name],cwd=R/'frontend' if name=='frontend' else R,env=env,stdout=f,stderr=subprocess.STDOUT)
 log=(O/(name+'-full.log')).read_text();return name,{'exitCode':p.returncode,'log':name+'-full.log','passed':re.findall(r'(\d+) passed',log),'skipped':re.findall(r'(\d+) skipped',log),'tests':re.findall(r'ℹ tests (\d+)',log),'nodePasses':re.findall(r'ℹ pass (\d+)',log),'nodeSkips':re.findall(r'ℹ skipped (\d+)',log)}
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
 for future in concurrent.futures.as_completed([pool.submit(run,n) for n in commands]):
  n,v=future.result();report['results'][n]=v;(O/'full-checks.json').write_text(json.dumps(report,indent=2)+'\n');print(n,json.dumps(v),flush=True)
assert git('rev-parse','HEAD')==source and not git('status','--porcelain')
report['finishedAt']=datetime.datetime.now(datetime.timezone.utc).isoformat();report['passed']=all(x['exitCode']==0 for x in report['results'].values());(O/'full-checks.json').write_text(json.dumps(report,indent=2)+'\n')
raise SystemExit(0 if report['passed'] else 1)
