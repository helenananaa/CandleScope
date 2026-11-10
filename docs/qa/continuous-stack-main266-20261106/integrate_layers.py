import json,os,subprocess,datetime,re
from pathlib import Path
ROOT=Path('/Users/ryanliang/.codex/worktrees/chart-strategy-sessions-20261104/CandleScope')
OUT=Path('/Users/ryanliang/CandleScope/output/development-goal-20261104/continuous-stack-main266-20261106')
plan=json.loads((OUT/'plan.json').read_text()); results=[]
PYTHON='/Users/ryanliang/.codex/worktrees/issue-152-output-range-20261102/CandleScope/output/issue-152-output-range-20261102/main226-native-test-env/bin/python'
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()
def save():
 (OUT/'layer-results.json').write_text(json.dumps({'plan':plan,'results':results},indent=2)+'\n')
def run(command,log,cwd=ROOT,env=None):
 with log.open('w') as stream:r=subprocess.run(command,cwd=cwd,env=env,stdout=stream,stderr=subprocess.STDOUT)
 if r.returncode:raise RuntimeError(f'Command failed:{r.returncode}; preserve {log}')
def tests(command,log,cwd,env):
 run(command,log,cwd,env);text=log.read_text();return {'command':command,'log':str(log),'exitCode':0,'passed':int(re.findall(r'(\d+) passed',text)[-1]) if re.findall(r'(\d+) passed',text) else sum(map(int,re.findall(r'ℹ tests (\d+)',text))),'skipped':int(re.findall(r'(\d+) skipped',text)[-1]) if re.findall(r'(\d+) skipped',text) else sum(map(int,re.findall(r'ℹ skipped (\d+)',text)))}
upstream=plan['actualMain']
for index,p in enumerate(plan['layerPlans']):
 assert not git('status','--porcelain','--untracked-files=normal'),'Do not discard dirty work'
 number=p['number'];branch=f'codex/stack-main266-{number}-20261106';folder=OUT/f'pr{number}';folder.mkdir(exist_ok=False)
 run(['git','switch','-c',branch,p['headRefOid']],folder/'switch.log')
 run(['git','merge','--no-edit','--no-stat',upstream],folder/'merge-upstream.log')
 if index==0:run(['git','merge','--no-edit','--no-stat',plan['reviewedPending266']],folder/'merge-reviewed266.log')
 head=git('rev-parse','HEAD');row={'number':number,'branch':branch,'remoteBranch':p['headRefName'],'priorHead':p['headRefOid'],'upstream':upstream,'source':head,'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'backendFocus':None,'frontendFocus':None};results.append(row);save()
 temp=Path('/tmp/candlescope-continuous-main266-20261106')/f'pr{number}';temp.mkdir(parents=True,exist_ok=False);(temp/'data').mkdir()
 env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':'packages/candlescope-plugin-sdk/src:packages/candlescope-backtest-sdk/src:backend','DATA_DIR':str(temp/'data'),'CANDLE_DATA_DIR':str(temp/'data'),'NATIVE_TEST_PINE_PYTHON':str(OUT/'pine/python')}
 backend_changed=index==0 or git('rev-parse',head+':backend')!=git('rev-parse',upstream+':backend')
 if backend_changed:
  suites=sorted(str(x.relative_to(ROOT)) for x in (ROOT/'backend/tests').glob('test_continuous*.py'));suites=list(dict.fromkeys(suites+p['backendFocus']))
  if index==0:suites+=['backend/tests/test_replay_imported_multimarket.py','backend/tests/test_local_data_api.py']
  command=[PYTHON,'-B','-m','pytest',*suites,'--basetemp='+str(temp/'pytest'),'-q','-rs'];row['backendFocus']=tests(command,folder/'backend-focus.log',ROOT,env)
 else:row['backendInheritedFromUpstream']=upstream;row['backendTreeEqual']=True
 if p['frontendFocus']:
  command=['node','scripts/run-frontend-tests.mjs',*p['frontendFocus']];row['frontendFocus']=tests(command,folder/'frontend-focus.log',ROOT/'frontend',env)
 assert git('rev-parse','HEAD')==head
 assert not git('status','--porcelain','--untracked-files=normal'),'Tests changed tracked source; inspect rather than reset'
 row['passed']=True;row['trees']={d:git('rev-parse',head+':'+d) for d in ['backend/app','frontend/src','packages','.github']};save()
 print(json.dumps({'pr':number,'source':head,'backendPassed':(row['backendFocus'] or {}).get('passed'),'frontendPassed':(row['frontendFocus'] or {}).get('passed'),'passed':True}),flush=True)
 upstream=head
print('ALL LAYER FOCUSED CHECKS PASS; full top qualification still required',flush=True)
