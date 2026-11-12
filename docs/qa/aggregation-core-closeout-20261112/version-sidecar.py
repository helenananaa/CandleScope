"""Controlled native version replacement; public responses are never substituted.

The packaged Electron frontend stays open. A private selection file replaces
only its owned child sidecar on the same HTTP endpoint and isolated data path.
"""
from __future__ import annotations
import json, os, runpy, signal, subprocess, sys, time
from pathlib import Path
from urllib.parse import urlsplit,parse_qsl

if __name__ == '__main__':
    if '--child' in sys.argv:
        config=json.loads(Path(sys.argv[2]).read_text());variant=sys.argv[3];generation=int(sys.argv[4])
        sys.path.insert(0,config['backends'][variant])
        os.chdir(config['backends'][variant])
        import ccxt.async_support as ccxt
        original=ccxt.Exchange.fetch
        async def fetch(self,url,method='GET',headers=None,body=None):
            parsed=urlsplit(url)
            if 'candle' not in parsed.path.lower() and 'kline' not in parsed.path.lower():
                return await original(self,url,method,headers,body)
            entry={'generation':generation,'variant':variant,'at':time.time(),
                'method':method,'host':parsed.hostname,'path':parsed.path,
                'query':[(k,v) for k,v in parse_qsl(parsed.query) if k.lower() not in {'token','secret','key','signature'}]}
            try:
                value=await original(self,url,method,headers,body)
                entry['success']=True
                if isinstance(value,dict) and isinstance(value.get('data'),list):
                    rows=value['data']
                    entry['returned']=[{'open_ms':int(row[0]),'confirmed':row[-1]=='1'} for row in rows if isinstance(row,list) and len(row)>=9 and str(row[0]).isdigit()]
                return value
            except BaseException as error:
                entry['success']=False;entry['error_type']=type(error).__name__;raise
            finally:
                with open(config['requests'],'a') as stream:stream.write(json.dumps(entry)+'\n')
        ccxt.Exchange.fetch=fetch
        sys.argv=['app.desktop_sidecar','--host','127.0.0.1','--port',str(config['port'])]
        runpy.run_module('app.desktop_sidecar',run_name='__main__')
        raise SystemExit

    config_path=Path(sys.argv[1]);config=json.loads(config_path.read_text());stop=False;child=None

    def stopping(*args):
        global stop
        stop=True
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,stopping)

    def end_child():
        global child
        if child is None:return
        if child.poll() is None:
            try:child.stdin.write(b'shutdown\n');child.stdin.flush()
            except (BrokenPipeError,OSError):pass
            try:child.wait(timeout=25)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid,signal.SIGKILL);child.wait()
        with open(config['generations'],'a') as f:f.write(json.dumps({'event':'stopped','pid':child.pid,'returncode':child.returncode,'at':time.time()})+'\n')
        child=None

    variant=None;generation=0
    try:
        while not stop:
            wanted=Path(config['selection']).read_text().strip()
            assert wanted in config['backends']
            if wanted!=variant:
                end_child();generation+=1;variant=wanted
                child=subprocess.Popen([sys.executable,'-u',__file__,'--child',str(config_path),variant,str(generation)],stdin=subprocess.PIPE,start_new_session=True)
                with open(config['generations'],'a') as f:f.write(json.dumps({'event':'started','pid':child.pid,'variant':variant,'generation':generation,'at':time.time()})+'\n')
            if child.poll() is not None:raise RuntimeError('sidecar exited before controlled switch')
            time.sleep(.1)
    finally:end_child()
