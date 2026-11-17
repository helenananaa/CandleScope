"""Verify exact package and correlate actual source, business WS and chart values."""
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys

root=Path(sys.argv[1]).resolve()
candidate=Path(sys.argv[2]).resolve()
receipt=json.loads((root/'acceptance.json').read_text())
manifest=json.loads((candidate/'package-source-manifest.json').read_text())
assert receipt['passed'] and receipt['sourceCommit']==manifest['product_head']
resources=candidate/'CandleScope.app/Contents/Resources'
for name,digest in manifest['files'].items():
    assert hashlib.sha256((resources/name).read_bytes()).hexdigest()==digest,name
assert hashlib.sha256((resources/'app.asar').read_bytes()).hexdigest()==manifest['app_asar_sha256']
subprocess.run(['codesign','--verify','--deep','--strict',str(candidate/'CandleScope.app')],check=True)
assert any(s['name']=='full-process-exit' for s in receipt['steps'])
frames=[json.loads(line) for line in (root/'business-frames.jsonl').read_text().splitlines()]
klines=[r for r in frames if r['message'].get('type')=='kline']
samples=json.loads((root/'actual-value-samples.json').read_text())
timeline=[json.loads(line) for line in (root/'recovery-timeline.jsonl').read_text().splitlines()]
evidence=[]
for phase in ('initial','resnapshot'):
    for interval in ('89m','97m','101m','10007m'):
        values=[s for s in samples if s['label']==phase and s['interval']==interval]
        matched=[]
        for value in values:
            bar=value['bar']
            candidates=[r for r in klines if r['at']<=value['at'] and r['message']['interval']==interval
                        and r['message']['data']['time']==bar['time']
                        and r['message']['data']['close']==bar['close']
                        and abs(r['message']['data']['volume']-bar['volume'])<1e-6]
            if candidates:
                row=candidates[-1]
                for field in ('open','high','low','close','volume','quote_volume','trades','taker_buy_base','taker_buy_quote'):
                    a,b=bar.get(field),row['message']['data'].get(field)
                    assert (a is None and b is None) or (a is not None and b is not None and abs(a-b)<=max(1e-6,abs(a)*1e-12)),(interval,field,a,b)
                assert value['point']['value']==bar['close'] and not bar['is_closed']
                assert row['message']['stream_version']['series']['interval']==interval
                matched.append({'sample_at':value['at'],'wire_at':row['at'],'close':bar['close'],
                                'volume':bar['volume'],'time':bar['time'],'version':row['message']['stream_version']})
        assert len({(s['time'],s['close'],s['volume']) for s in matched})>=3,(phase,interval,len(matched))
        source_matches=[]
        screen_matches=[]
        source_ws_matches=[]
        for value in values:
            sample=next(s for s in timeline if s['label']==phase and s['at']==value['at'])
            if sample.get('displays'):
                cell_id=next(v['cellId'] for v in sample['views'] if v['interval']==interval)
                display=next(d for d in sample['displays'] if d['cellId']==cell_id)
                rendered=re.search(r'\bC\s*([0-9,]+\.[0-9]+)',display['text'])
                if rendered and abs(float(rendered[1].replace(',',''))-value['bar']['close'])<.005:
                    screen_matches.append({'at':value['at'],'close':value['bar']['close'],'rendered_C':rendered[1]})
            inputs=sample['source']['data']
            if (inputs and inputs[-1]['close']==value['bar']['close']
                    and value['bar']['time'] <= inputs[-1]['time'] < value['bar']['time']+int(interval[:-1])*60):
                source_matches.append({'at':value['at'],'source':inputs[-1], 'target':value['bar']})
        for value in values:
            candidates=[r for r in klines if r['at']<=value['at'] and r['message']['interval']=='1m'
                        and r['message'].get('market_type')=='futures'
                        and r['message']['data']['close']==value['bar']['close']
                        and value['bar']['time'] <= r['message']['data']['time'] < value['bar']['time']+int(interval[:-1])*60]
            if candidates:
                source_ws_matches.append({'sample_at':value['at'],'source_wire_at':candidates[-1]['at'],
                                          'source_message':candidates[-1]['message'],'target':value['bar']})
        assert source_matches or source_ws_matches,(phase,interval,'no actual 1m to target value match')
        if any(t.get('displays') for t in timeline):
            assert screen_matches,(phase,interval,'no rendered C value match')
        evidence.append({'phase':phase,'interval':interval,'matched_ws_chart_js':matched,
                         'matched_canonical_source_to_target':source_matches,'matched_screen_headers':screen_matches,'matched_source_ws_to_target':source_ws_matches})
log=(root/'profile/logs/backend-sidecar.log').read_text()
result={'passed':True,'source_commit':receipt['sourceCommit'],'backend_files_verified':len(manifest['files']),
        'app_asar_sha256':manifest['app_asar_sha256'],'actual_total_elapsed_ms':receipt['actualTotalElapsedMs'],
        'kline_business_frames':len(klines),'evidence':evidence,
        'generation_expired_count':log.count('history target generation expired'),
        'recovery_notifications':log.count('Consumer recovery required:'),
        'scope':'Real source/current target/business WS/chart store/JS values, before and after renderer resnapshot. Not cold or ten-minute acceptance.'}
assert result['generation_expired_count']==0
(root/'value-chain.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='evidence'}))
