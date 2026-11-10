import json, os, signal, socket, subprocess, time, urllib.request
from pathlib import Path

ROOT=Path('/Users/ryanliang/.codex/worktrees/chart-strategy-sessions-20261104/CandleScope')
OUT=Path('/Users/ryanliang/CandleScope/output/development-goal-20261104')
label=os.environ.get('CANDLESCOPE_RESEARCH_RUN_LABEL','research-return-main261-browser-20261106')
assert label in ['research-return-main261-browser-20261106','research-return-main261-browser-ready-20261106']
RUN=OUT/label
PY='/Users/ryanliang/.codex/worktrees/issue-152-output-range-20261102/CandleScope/output/issue-152-output-range-20261102/main226-native-test-env/bin/python'
assert subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()=='codex/research-selected-version-main261-20261106'
source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
RUN.mkdir(exist_ok=False)
for port in [23183,23184]:
    with socket.socket() as sock: assert sock.connect_ex(('127.0.0.1',port))!=0, f'Port {port} is already owned'
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH='packages/candlescope-plugin-sdk/src:packages/candlescope-backtest-sdk/src:backend',
         DATA_DIR=str(RUN/'data'),CANDLE_DATA_DIR=str(RUN/'data'),RESEARCH_RETURN_QA_PROFILE=str(RUN/'profile'),CORS_ORIGINS='http://127.0.0.1:23183')
venv=dict(env,VITE_API_BASE='http://127.0.0.1:23184/api/v1',VITE_API_PROXY_TARGET='http://127.0.0.1:23184')
benv=dict(env,RESEARCH_RETURN_QA_OUT=str(RUN/'browser'),CANDLESCOPE_PLAYWRIGHT_PACKAGE=str(OUT/'native-tooling-20261106/package.json'))
commands=[([PY,'-B','docs/qa/research-selected-version-20261105/server.py'],ROOT,env,'server'),
          (['node','node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','23183','--strictPort'],ROOT/'frontend',venv,'vite')]
owned=[];observed={};files=[];result={'source':source,'scope':'Real production composition fixture with deterministic local BAR/stream inputs; not Native or public-market','browserPassed':False}
def capture():
    lines=subprocess.check_output(['ps','-Ao','pid=,ppid=,command='],text=True).splitlines();rows={}
    for line in lines:
        p=line.strip().split(None,2)
        if len(p)==3:rows[int(p[0])]={'pid':int(p[0]),'ppid':int(p[1]),'command':p[2]}
    roots={p.pid for _,p in owned};selected=set(roots)
    while True:
        children={pid for pid,row in rows.items() if row['ppid'] in selected}
        if children<=selected:break
        selected|=children
    observed.update({pid:rows[pid] for pid in selected if pid in rows})
def ready(url):
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        capture()
        assert all(p.poll() is None for _,p in owned), 'Owned service exited during startup'
        try:
            with urllib.request.urlopen(url,timeout=1) as r:
                if r.status==200:return
        except Exception:pass
        time.sleep(.25)
    raise RuntimeError('Local fixture readiness timed out')
try:
    for args,cwd,environment,name in commands:
        f=(RUN/f'{name}.log').open('w');files.append(f)
        p=subprocess.Popen(args,cwd=cwd,env=environment,stdout=f,stderr=subprocess.STDOUT,start_new_session=True);owned.append((name,p))
    ready('http://127.0.0.1:23184/api/v1/qa/audit');ready('http://127.0.0.1:23183/tests/fixtures/research-return/entry.html')
    f=(RUN/'browser.log').open('w');files.append(f)
    browser=subprocess.Popen(['node','docs/qa/research-selected-version-20261105/browser.mjs'],cwd=ROOT,env=benv,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
    owned.append(('browser',browser));deadline=time.monotonic()+150
    while browser.poll() is None:
        capture();assert time.monotonic()<deadline,'Browser deadline exceeded';time.sleep(.5)
    result['browserExitCode']=browser.returncode
    if (RUN/'browser/receipt.json').exists():
        receipt=json.loads((RUN/'browser/receipt.json').read_text());result.update(browserPassed=receipt.get('passed',False),steps=len(receipt['steps']),errors=receipt['errors'],failure=receipt.get('failure'))
    assert browser.returncode==0 and result['browserPassed'], 'Browser qualification failed; retain raw receipt'
    with urllib.request.urlopen('http://127.0.0.1:23184/api/v1/qa/audit',timeout=10) as response:
        (RUN/'final-backend-audit.json').write_bytes(response.read())
except Exception as e:
    result['orchestratorFailure']=repr(e)
finally:
    capture();(RUN/'processes-before-shutdown.json').write_text(json.dumps(list(observed.values()),indent=2)+'\n')
    for name,p in reversed(owned):
        if p.poll() is None:p.send_signal(signal.SIGINT)
    deadline=time.monotonic()+60
    while any(p.poll() is None for _,p in owned) and time.monotonic()<deadline:
        capture();time.sleep(.25)
    result['roots']=[{'name':name,'pid':p.pid,'exitCode':p.poll()} for name,p in owned]
    def alive(pid):
        try:os.kill(pid,0);return True
        except ProcessLookupError:return False
    result['remainingOwnedPids']=[pid for pid in observed if alive(pid)]
    result['ownedPidsIndependentlyAbsent']=not result['remainingOwnedPids']
    result['shutdown']=json.loads((RUN/'profile/shutdown.json').read_text()) if (RUN/'profile/shutdown.json').exists() else None
    for f in files:f.close()
    result['qualified']=result['browserPassed'] and result['ownedPidsIndependentlyAbsent'] and bool(result['shutdown'] and result['shutdown']['closed'] and not result['shutdown']['leases'] and result['shutdown']['research_unchanged'])
    (RUN/'qualification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
raise SystemExit(0 if result['qualified'] else 1)
