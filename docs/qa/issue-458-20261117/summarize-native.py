"""Summarize a stopped scoped native run; keep joint readiness unqualified."""
import collections
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

out = Path(sys.argv[1])
run, candidate = out/'native-cold', out/'candidate'
a = json.loads((run/'acceptance.json').read_text())
exit_step = next(s for s in a['steps'] if s['name']=='full-process-exit')
observation = next(s['evidence'] for s in a['steps'] if s['name']=='source-routing-observed')
manifest = json.loads((candidate/'package-source-manifest.json').read_text())
app = candidate/'CandleScope.app'
mismatches = [name for name,digest in manifest['files'].items()
              if hashlib.sha256((app/'Contents/Resources'/name).read_bytes()).hexdigest()!=digest]
signature = subprocess.run(['codesign','--verify','--deep','--strict',str(app)],capture_output=True,text=True)
verified = {'product':manifest['product_head'],'backend_files':len(manifest['files']),
            'backend_mismatches':mismatches,'strict_signature_passed':signature.returncode==0,
            'signature_output':signature.stdout+signature.stderr,
            'app_asar_matches':hashlib.sha256((app/'Contents/Resources/app.asar').read_bytes()).hexdigest()==manifest['app_asar_sha256'],
            'hardware':'MacBookAir10,1 / Apple M1 / 16 GiB / 8 logical CPUs','os':platform.platform()}
assert not mismatches and verified['strict_signature_passed'] and verified['app_asar_matches']
assert manifest['product_head'] == a['sourceCommit']
(out/'package-verification.json').write_text(json.dumps(verified,indent=2)+'\n')
traffic = json.loads((run/'traffic.json').read_text())
queries = [r for r in traffic['responses'] if '/api/v1/klines/' in r['url'] and 'result' in r]
fast = [r for r in queries if r['result'].get('metadata',{}).get('canonical_target_snapshot')]
observed = []
for r in fast:
    m = r['result']['metadata']
    observed.append({'at_ms':r['observedAt'],'url':r['url'],'count':r['result']['count'],
                     'complete':r['result']['complete'],
                     'metadata':{k:v for k,v in m.items() if k.startswith(('canonical_','base_storage','target_storage','target_materialized'))}})
limits = {'max_local_source_budget':max((r['metadata'].get('canonical_local_repair_source_budget',0) for r in observed),default=0),
          'max_count_probes':max((r['metadata'].get('canonical_local_probe_reads',0) for r in observed),default=0),
          'zero_base_decode_responses':sum(r['metadata'].get('base_storage_rows')==0 for r in observed)}
assert observed and limits['max_local_source_budget']<=2048 and limits['max_count_probes']<=8
log = (run/'profile/logs/backend-sidecar.log').read_text()
rejections = collections.Counter(line.split('StaleAcquisition: ',1)[1] for line in log.splitlines() if 'StaleAcquisition: ' in line)
n = json.loads((run/'numeric.json').read_text())
summary = {'product':a['sourceCommit'],'scope':'macOS retained-runtime cold-profile scoped observation; no F463 joint qualification',
           'input':a['input'],'demand_started_at_ms':a['demandStartedAtMs'],
           'observation_ended_at_ms':a['observationEndedAtMs'],'actual_total_observed_ms':a['actualTotalElapsedMs'],
           'observation_censored':not a['firstReadinessObserved'],'net_readiness_ms':None,'net_readiness_qualified':False,
           'startup':'separate launch phase before demand; exact startup duration not instrumented',
           'cells':[{'interval':c['session']['interval'],**{k:c['runtime'].get(k) for k in ['barCount','marketReady','indicatorsReady','loading']}}
                    for c in observation['workspace']['cells']],
           'observed_kline_responses':len(queries),'canonical_snapshot_responses':len(fast),'observed_limits':limits,
           'revision_rejection_messages':dict(rejections),
           'history_target_generation_expired_trace_lines':log.count('BlockRevisionChanged: history target generation expired'),
           'numeric_passed':n['passed'],
           'numeric_closed_targets':{r['interval']:r['checked_closed_targets'] for r in n['per_interval']},
           'process_exit_elapsed_ms':exit_step['evidence']['elapsedMs']}
(out/'native-queries.json').write_text(json.dumps(observed,indent=2)+'\n')
(out/'native-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary))
