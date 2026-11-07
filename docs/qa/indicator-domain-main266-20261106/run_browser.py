from pathlib import Path
import subprocess,json,os,time,signal,socket,urllib.request
R=Path('/Users/ryanliang/.codex/worktrees/chart-strategy-sessions-20261104/CandleScope')
O=Path('/Users/ryanliang/CandleScope/output/development-goal-20261104/indicator-domain-main266-20261106')
B=O/'browser';B.mkdir(exist_ok=False);(B/'data').mkdir()
PY='/Users/ryanliang/.codex/worktrees/issue-152-output-range-20261102/CandleScope/output/issue-152-output-range-20261102/main226-native-test-env/bin/python'
port=18747
with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',port))!=0
source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip();assert source=='26590df1bd2a53c21fa009e070cd5a897e1fcbd2'
previous=json.loads((O/'combined-checks.json').read_text());env={**os.environ,**previous['env'],'DATA_DIR':str(B/'data'),'CANDLE_DATA_DIR':str(B/'data')}
benv={**env,'VITE_API_BASE':f'http://127.0.0.1:{port}/api/v1'}
logs=[];owned=[];observed={};report={'source':source,'scope':'Actual current-source React renderer/HTTP/WS/DataManager/SQLite/source SDK/Pine core; controlled local BAR feed, not Native/public-market'}
def capture():
 rows={}
 for s in subprocess.check_output(['ps','-Ao','pid=,ppid=,command='],text=True).splitlines():
  p=s.strip().split(None,2)
  if len(p)==3:rows[int(p[0])]={'pid':int(p[0]),'ppid':int(p[1]),'command':p[2]}
 selected={p.pid for _,p in owned}
 while True:
  children={pid for pid,x in rows.items() if x['ppid'] in selected}
  if children<=selected:break
  selected|=children
 observed.update({p:rows[p] for p in selected if p in rows})
def start(name,args,cwd,environment):
 f=(B/(name+'.log')).open('w');logs.append(f);p=subprocess.Popen(args,cwd=cwd,env=environment,stdout=f,stderr=subprocess.STDOUT,start_new_session=True);owned.append((name,p));return p
try:
 server=start('server',[PY,'-B','docs/qa/indicator-calculation-owner-20261105/chart_browser_app.py',str(B/'fixtures'),str(port)],R,env)
 deadline=time.monotonic()+60
 while True:
  capture();assert server.poll() is None,'Server exited during startup'
  try:
   with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/v1/fixture/state',timeout=1) as response:
    if response.status==200:break
  except Exception:pass
  assert time.monotonic()<deadline,'Server readiness timeout';time.sleep(.25)
 browser=start('browser',['node','scripts/frontend-script-integration.mjs','--chart-calculation','--out',str(B/'frontend')],R/'frontend',benv)
 deadline=time.monotonic()+240
 while browser.poll() is None:
  capture();assert time.monotonic()<deadline,'Browser observation deadline';time.sleep(.5)
 report['browserExitCode']=browser.returncode;assert browser.returncode==0,'Retain failed browser output'
except Exception as e:report['failure']=repr(e)
finally:
 capture();(B/'observed-processes.json').write_text(json.dumps(list(observed.values()),indent=2)+'\n')
 for name,p in reversed(owned):
  if p.poll() is None:p.send_signal(signal.SIGINT)
 deadline=time.monotonic()+60
 while any(p.poll() is None for _,p in owned) and time.monotonic()<deadline:capture();time.sleep(.25)
 report['roots']=[{'name':name,'pid':p.pid,'exitCode':p.poll()} for name,p in owned]
 def alive(pid):
  try:os.kill(pid,0);return True
  except ProcessLookupError:return False
 report['remainingOwnedPids']=[p for p in observed if alive(p)]
 report['shutdown']=json.loads((B/'fixtures/shutdown.json').read_text()) if (B/'fixtures/shutdown.json').exists() else None
 report['qualified']=report.get('browserExitCode')==0 and not report['remainingOwnedPids'] and report['shutdown'] is not None and all(p['exitCode']==0 for p in report['roots'])
 for f in logs:f.close()
 (B/'qualification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
raise SystemExit(0 if report['qualified'] else 1)
