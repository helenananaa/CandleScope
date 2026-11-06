from pathlib import Path
import json,subprocess,os,time,datetime,signal
R=Path('/Users/ryanliang/.codex/worktrees/chart-strategy-sessions-20261104/CandleScope')
BASE=Path('/Users/ryanliang/CandleScope/output/development-goal-20261104')
N=BASE/'indicator-domain-main266-native-20261106';STATE=BASE/'state.json'
source='26590df1bd2a53c21fa009e070cd5a897e1fcbd2'
def gate():
 deadlines=[datetime.datetime.fromisoformat('2026-11-06T10:12:49.286+00:00').timestamp()]
 for p in [STATE,Path('/Users/ryanliang/CandleScope/output/backend-goal-20261102/STATE.json'),N/'new-cooldown.json']:
  if p.exists():
   s=json.loads(p.read_text());d=s.get('public_cooldown',{}).get('retry_not_before_utc') or s.get('retry_not_before_utc')
   if d:deadlines.append(datetime.datetime.fromisoformat(d.replace('Z','+00:00')).timestamp())
 return max(deadlines)
assert not (N/'profile').exists()
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()==source
ready={'source':source,'pid':os.getpid(),'state':'waiting for existing public cooldown; no app launched','notBefore':datetime.datetime.fromtimestamp(gate(),datetime.timezone.utc).isoformat()}
(N/'launch-wait.json').write_text(json.dumps(ready,indent=2)+'\n');print(json.dumps(ready),flush=True)
while time.time()<gate():time.sleep(min(1,max(.01,gate()-time.time())))
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()==source
assert not subprocess.check_output(['git','diff','--name-only','HEAD','--','backend','frontend','packages','.github'],cwd=R,text=True).strip()
s=json.loads(STATE.read_text());assert s.get('activeNativeOwner') is None;s['activeNativeOwner']={'scope':'227 current-main LIVE counter/deletion/parity/save/fullquit/restart','source':source,'root':str(N),'launchAt':datetime.datetime.now(datetime.timezone.utc).isoformat()};STATE.write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n')
env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','CANDLESCOPE_BATCH1_QA_ROOT':str(N),'CANDLESCOPE_PLAYWRIGHT_PACKAGE':str(BASE/'native-tooling-20261106/package.json')}
observed={}
def capture(root):
 rows={}
 for line in subprocess.check_output(['ps','-Ao','pid=,ppid=,command='],text=True).splitlines():
  p=line.strip().split(None,2)
  if len(p)==3:rows[int(p[0])]={'pid':int(p[0]),'ppid':int(p[1]),'command':p[2]}
 selected={root}
 while True:
  children={p for p,v in rows.items() if v['ppid'] in selected}
  if children<=selected:break
  selected|=children
 observed.update({p:rows[p] for p in selected if p in rows})
with (N/'native.log').open('w') as f:
 proc=subprocess.Popen(['node','docs/qa/indicator-domain-native-20261106/native-acceptance.mjs'],cwd=R,env=env,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
 while proc.poll() is None:capture(proc.pid);time.sleep(.25)
(N/'observed-processes.json').write_text(json.dumps(list(observed.values()),indent=2)+'\n')
receipt=json.loads((N/'acceptance.json').read_text()) if (N/'acceptance.json').exists() else {}
def alive(pid):
 try:os.kill(pid,0);return True
 except ProcessLookupError:return False
remaining=[p for p in observed if alive(p)]
result={'source':source,'nativeExitCode':proc.returncode,'passed':receipt.get('passed',False),'failure':receipt.get('failure'),'exitFailure':receipt.get('exitFailure'),'steps':len(receipt.get('steps',[])),'observedOwnedPids':list(observed),'remainingObservedPids':remaining,'completedAt':datetime.datetime.now(datetime.timezone.utc).isoformat()}
(N/'independent-post-run.json').write_text(json.dumps(result,indent=2)+'\n')
if not remaining:
 s=json.loads(STATE.read_text());s['activeNativeOwner']=None;STATE.write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result),flush=True)
raise SystemExit(0 if result['passed'] and not remaining else 1)
