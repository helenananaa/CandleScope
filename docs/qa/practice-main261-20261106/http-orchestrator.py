import json,os,signal,subprocess,time,urllib.request
from pathlib import Path

ROOT=Path('/Users/ryanliang/.codex/worktrees/chart-strategy-sessions-20261104/CandleScope')
label=os.environ.get('CANDLESCOPE_PRACTICE_HTTP_ROOT_NAME','pr223-main261-http-20261106')
assert label in ['pr223-main261-http-20261106','pr223-main261-http-ready-20261106']
OUT=Path('/Users/ryanliang/CandleScope/output/development-goal-20261104')/label
OUT.mkdir(exist_ok=False)
QA=ROOT/'docs/qa/practice-main261-20261106'
source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
PY='/Users/ryanliang/.codex/worktrees/issue-152-output-range-20261102/CandleScope/output/issue-152-output-range-20261102/main226-native-test-env/bin/python'
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH='packages/candlescope-plugin-sdk/src:packages/candlescope-backtest-sdk/src:backend',DATA_DIR=str(OUT/'data'),CANDLE_DATA_DIR=str(OUT/'data'),CANDLESCOPE_QA_STATE_ROOT=str(OUT/'state'))
known={};roots=[];result={'source':source,'scope':'Actual HTTP/SQLite and unmodified frontend data pool/transport; deterministic local BAR inputs and outbound network guard; no Native/public-market','phases':[]}
def capture(processes):
    rows={}
    for line in subprocess.check_output(['ps','-Ao','pid=,ppid=,command='],text=True).splitlines():
        bits=line.strip().split(None,2)
        if len(bits)==3:rows[int(bits[0])]={'pid':int(bits[0]),'ppid':int(bits[1]),'command':bits[2]}
    selected={p.pid for p in processes}
    while True:
        children={pid for pid,row in rows.items() if row['ppid'] in selected}
        if children<=selected:break
        selected|=children
    known.update({pid:rows[pid] for pid in selected if pid in rows})
def live(pid):
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False
try:
    for phase in ['flow','restart']:
        server=None;client=None;handles=[]
        try:
            log=OUT/f'{phase}-server.log';handle=log.open('w');handles.append(handle)
            server=subprocess.Popen([PY,'-B',str(QA/'http_server.py')],cwd=ROOT,env=env,stdout=handle,stderr=subprocess.STDOUT,start_new_session=True)
            roots.append(server);port=None;deadline=time.monotonic()+30
            while port is None:
                capture([server]);assert server.poll() is None,'Server exited before readiness'
                for line in log.read_text().splitlines():
                    if line.startswith('{'):
                        row=json.loads(line)
                        if row.get('ready'):port=row['port']
                assert time.monotonic()<deadline,'Server readiness timeout';time.sleep(.1)
            base=f'http://127.0.0.1:{port}'
            with urllib.request.urlopen(base+'/qa/diagnostics',timeout=10) as response:assert response.status==200
            handle=(OUT/f'{phase}-client.log').open('w');handles.append(handle)
            client=subprocess.Popen([str(ROOT/'frontend/node_modules/.bin/tsx'),str(QA/'http_client.mts'),phase],cwd=ROOT,env=dict(env,CANDLESCOPE_QA_HTTP_BASE=base),stdout=handle,stderr=subprocess.STDOUT,start_new_session=True)
            roots.append(client);deadline=time.monotonic()+60
            while client.poll() is None:
                capture([server,client]);assert time.monotonic()<deadline,'Client timeout';time.sleep(.2)
            assert client.returncode==0,f'{phase} client failed; retain log'
            result['phases'].append({'name':phase,'port':port,'serverPid':server.pid,'clientPid':client.pid,'clientExit':client.returncode})
        finally:
            for proc in [client,server]:
                if proc is not None and proc.poll() is None:proc.send_signal(signal.SIGINT)
            deadline=time.monotonic()+30
            while any(p is not None and p.poll() is None for p in [client,server]) and time.monotonic()<deadline:
                capture([p for p in [client,server] if p is not None]);time.sleep(.1)
            for h in handles:h.close()
            assert all(p is None or p.poll() is not None for p in [client,server]),'Owned process still running'
            assert server is not None and server.returncode==0,'Server shutdown failed'
            shutdown_rows=[json.loads(line) for line in log.read_text().splitlines() if line.startswith('{')]
            shutdown=next(row for row in shutdown_rows if row.get('shutdown_complete'))
            assert shutdown['manager']['closed'] and shutdown['manager']['read_jobs']==0
            assert shutdown['manager']['subscriptions']==0 and shutdown['network']['blocked_attempts']==0
            result['phases'][-1]['shutdown']=shutdown
except Exception as e:
    result['failure']=repr(e)
result['roots']=[{'pid':p.pid,'exitCode':p.poll()} for p in roots]
result['observedProcesses']=list(known.values());result['remainingPids']=[pid for pid in known if live(pid)]
result['passed']=len(result['phases'])==2 and not result['remainingPids'] and 'failure' not in result
(OUT/'qualification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='observedProcesses'}),flush=True)
raise SystemExit(0 if result['passed'] else 1)
