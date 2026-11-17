"""Phase-memory progress is distinct from the unchanged joint readiness gate."""
from pathlib import Path
import collections,json,sys,xml.etree.ElementTree as ET

root=Path(sys.argv[1]);native=root/'native-cold-final'
identity=json.loads((root/'regression-identity.json').read_text())
tests=list(ET.parse(root/'regression-final.xml').getroot().iter('testcase'))
bad=[t.attrib for t in tests if any(t.find(k) is not None for k in ('failure','error','skipped'))]
summary=json.loads((native/'summary.json').read_text())
receipt=json.loads((native/'acceptance.json').read_text())
rows=[json.loads(l) for l in (native/'acceptance-timeline.jsonl').open()]
chunks=json.loads((native/'scheduler-chunks.json').read_text())
routes=json.loads((native/'source-routes.json').read_text())
large_routes=[r for r in routes if r.get('requested_interval')=='10007m'
    and r.get('status')=='completed' and r.get('fetched_rows',0)>0]
first_source=min((r['observed_at_ms'] for r in large_routes),default=None)
source=json.loads((native/'source-numeric.json').read_text())
large_source=next(c for c in source['per_chart'] if c['interval']=='10007m')
large_oracle={k:large_source[k] for k in ('interval','displayed','verified_closed')}
large_oracle.update(unverified=len(large_source['unverified']),mismatches=len(large_source['mismatches']))
reasons=collections.Counter(c.get('defer_reason') for c in chunks)
resource_replans={k:v for k,v in reasons.items() if k and (k=='local_memory_admission' or k.startswith('local_executor'))}
memory=[r['diagnostics']['backfill_engine']['working_set_admission'] for r in rows]
log=(native/'profile/logs/backend-sidecar.log').read_text()
errors=collections.Counter(l for l in log.splitlines() if l.startswith(
    ('app.data_engine.memory_budget.MemoryBudgetExceeded:','app.core.bounded_executor.ExecutorBusyError:')))
checks=dict(regression_passed=not bad and identity['returncode']==0 and bool(tests),
    immutable_source=identity['source_unchanged'],native_product_matches=identity['product_head']==summary['product_head'],
    cold_without_seed=summary['pre_demand_canonical_rows']==0,full_exit=summary['full_exit_observed'],
    work_and_plan_claims_within_limits=all(m['reserved_bytes']<=m['limit_bytes']
        and m['plan_reserved_bytes']<=m['plan_limit_bytes']
        and m['shared_reserved_bytes']<=m['shared_limit_bytes'] for m in memory),
    no_resource_replans=not resource_replans,no_capacity_exceptions=not errors,
    large_prime_successful_source_receipts=bool(large_routes),
    large_prime_real_closed_outputs=large_source['verified_closed']>0,
    large_prime_observed_outputs_match=not large_source['mismatches'] and not large_source['unverified'])
result=dict(scope='Fair phase/page memory admission and large-prime progress; not full #447/#463 readiness',
    product_head=identity['product_head'],passed=all(checks.values()),checks=checks,tests=len(tests),
    first_large_prime_successful_source_receipt_ms=(first_source-receipt['demandStartedAtMs'] if first_source else None),
    source_receipt_timing='Completed task receipt, not physical HTTP start or exact critical-path latency',
    successful_large_prime_routes=len(large_routes),large_prime_source_oracle=large_oracle,
    max_work_bytes=max(m['reserved_bytes'] for m in memory),max_plan_bytes=max(m['plan_reserved_bytes'] for m in memory),
    max_shared_reserved_bytes=max(m['shared_reserved_bytes'] for m in memory),
    resource_replans=resource_replans,capacity_exceptions=dict(errors),
    phase_resumptions=summary['last_phase_resumptions'],
    startup_elapsed_ms=receipt['startupElapsedMs'],actual_total_observation_ms=receipt['actualTotalElapsedMs'],
    cold_observation_elapsed_ms=receipt['coldObservationElapsedMs'],joint_cold_ready=summary['cold_observed_ready'],
    joint_full_lifecycle_passed=False,net_readiness_ms=None,
    qualification='Only scoped progress/continuation. All charts still require original 128/127, fields, indicators/drawing, net <=3s and full lifecycle under #463. Native totals include observation, extra sampling and quit.')
(root/'scoped-acceptance.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='large_prime_source_oracle'}))
sys.exit(0 if result['passed'] else 1)
