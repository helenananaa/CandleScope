from pathlib import Path
import pytest
patterns=['test_bar_agg*.py','test_interval_rout*.py','test_component*.py','test_shared*.py','test_history_prefix*.py','test_kline*.py','test_query*.py','test_bar_cache*.py','test_data_manager*.py','test_bar_delivery*.py','test_source_revision*.py','test_custom*.py','test_aggregation_core.py','test_history_block_reader.py','test_mixed*.py','test_recovery*.py','test_backfill*.py','test_history_archive*.py','test_pyne_removal.py','test_fixed_anchor.py','test_calendar_basis.py','test_interval_resolution.py','test_interval_policy_consistency.py','test_data_engine_phase1_boundaries.py','test_cache_metadata_budget.py','test_gc_execution_safety.py','test_storage_retention_gc.py','test_consumer_recovery.py','test_realtime_target_lifecycle.py','test_realtime_handoff_accounting.py','test_canonical_history_stream.py','test_manual_history*.py','test_interval_policy*.py']
files=sorted({str(p) for pattern in patterns for p in Path('backend/tests').glob(pattern)})
if __name__=='__main__':
    raise SystemExit(pytest.main(['-q',*files,'--junitxml=output/realtime-handoff-accounting-126-20261112/tests.xml']))
