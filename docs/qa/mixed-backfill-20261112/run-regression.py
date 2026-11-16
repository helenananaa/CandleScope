from pathlib import Path
import pytest
patterns = ['test_backfill*.py','test_history_archive*.py','test_mixed_backfill*.py','test_history_cover*.py','test_binance_backfill_fetcher.py','test_public_transport_loopback.py']
names = '''test_default_mixed_history_query test_mixed_history_precedence test_exchange_capabilities_v2 test_custom_history_streaming test_custom_interval_phase1 test_custom_materialization_ownership test_custom_interval_listing_boundary test_custom_aggregate_blocks test_query_engine_paths test_materialized_history_probe test_query_cache_fencing test_history_revision_admission test_mixed_history_reader test_history_block_reader test_interval_resolution test_pyne_removal test_shared_aggregation_blocks test_shared_blocks_integration test_aggregation_core test_source_revision_pipeline test_kline_revision_contract test_interval_policy_consistency test_fixed_anchor test_calendar_basis test_bar_aggregator_contracts test_component_incremental'''.split()
files = {str(p) for pat in patterns for p in Path('backend/tests').glob(pat)} | {f'backend/tests/{n}.py' for n in names}
if __name__ == '__main__':
    raise SystemExit(pytest.main(['-q',*sorted(files),'--junitxml=output/mixed-backfill-20261112/tests-product.xml']))
