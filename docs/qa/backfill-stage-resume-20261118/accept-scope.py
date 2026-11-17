"""Judge resource-stage continuation separately from joint native readiness."""
from pathlib import Path
import collections,json,sys,xml.etree.ElementTree as ET

root=Path(sys.argv[1])
identity=json.loads((root/'regression-identity.json').read_text())
xml=ET.parse(root/'regression-final.xml').getroot()
tests=list(xml.iter('testcase'))
failed=[t.attrib for t in tests if any(t.find(n) is not None for n in ('failure','error','skipped'))]
required={
    'test_resource_wait_after_planning_resumes_same_engine_and_plan',
    'test_preparation_queue_wait_preserves_mixed_planning_cursor',
    'test_deferred_attempt_drops_page_loans_before_another_planner_needs_capacity',
    'test_repeated_typed_view_rejections_reuse_received_input_until_canonical_adoption',
    'test_cancelling_original_grant_owner_keeps_shared_input_funded_until_adoption',
    'test_source_deletion_denies_old_receipt_until_a_new_physical_acquisition',
    'test_concurrent_first_rest_pages_migrate_original_raw_journal_once',
}
names={t.get('name') for t in tests}
missing=sorted(required-names)
native=json.loads((root/'native-cold-final/summary.json').read_text())
receipt=json.loads((root/'native-cold-final/acceptance.json').read_text())
log=(root/'native-cold-final/profile/logs/backend-sidecar.log').read_text()
rows=[json.loads(line) for line in (root/'native-cold-final/acceptance-timeline.jsonl').open()]
reasons=collections.Counter(c.get('defer_reason') for c in json.loads(
    (root/'native-cold-final/scheduler-chunks.json').read_text()))
forbidden={k:v for k,v in reasons.items() if k and (k=='local_memory_admission' or k.startswith('local_executor'))}
capacity_errors=collections.Counter(line for line in log.splitlines() if line.startswith(
    ('app.data_engine.memory_budget.MemoryBudgetExceeded:', 'app.core.bounded_executor.ExecutorBusyError:')))
# A claim above the fixed owner limit cannot ever receive a permit. Existing
# composed-repair refinement must split it; it is not transient backpressure.
hard_limit='app.data_engine.memory_budget.MemoryBudgetExceeded: execution working set exceeds the owner budget'
transient_errors={k:v for k,v in capacity_errors.items() if k!=hard_limit}
checks={
    'regression_passed':bool(tests) and not failed and identity['returncode']==0,
    'source_unchanged_during_regression':identity['source_unchanged'],
    'required_regressions_present':not missing,
    'native_matches_tested_product':identity['product_head']==native['product_head'],
    'native_cold_without_market_seed':native['pre_demand_canonical_rows']==0,
    'native_full_exit':native['full_exit_observed'],
    'native_resource_waits_exercised':max(r['diagnostics']['backfill_engine']['working_set_admission']['work_waits'] for r in rows)>0,
    'native_continuations_observed':native['last_phase_resumptions']>0,
    'native_no_resource_replan_receipts':not forbidden,
    'native_no_transient_capacity_exceptions':not transient_errors,
}
result=dict(scope='Resource permits resume the same stage; not #447/#463 joint readiness',
    product_head=identity['product_head'],passed=all(checks.values()),checks=checks,
    tests=len(tests),failed_tests=failed,missing_required_tests=missing,
    native_resource_replan_receipts=forbidden,phase_resumptions=native['last_phase_resumptions'],
    native_transient_capacity_exceptions=transient_errors,
    native_hard_working_set_limit_rejections=capacity_errors.get(hard_limit,0),
    actual_total_observation_ms=native['actual_total_elapsed_ms'],startup_elapsed_ms=receipt['startupElapsedMs'],
    cold_observation_elapsed_ms=native['cold_observation_elapsed_ms'],
    joint_native_ready=native['cold_observed_ready'],net_readiness_ms=None,
    joint_acceptance_open=['447','463'],
    warning='Resource-stage checks do not certify all charts, lifecycle or net <=3s. Native totals include observation, post-sampling and quit; concurrent local test load is not a controlled performance comparison.')
(root/'scoped-acceptance.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
sys.exit(0 if result['passed'] else 1)
