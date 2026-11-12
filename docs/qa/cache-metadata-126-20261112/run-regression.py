from pathlib import Path
import pytest
patterns = ['test_bar_cache*.py','test_query*.py','test_kline*.py','test_data_manager_gc.py','test_gc_execution_safety.py','test_cache_metadata_budget.py','test_shared*.py','test_mixed*.py','test_custom*.py','test_history_revision_admission.py','test_bar_delivery*.py','test_storage_retention_gc.py','test_data_engine_phase1_boundaries.py','test_pyne_removal.py','test_backfill*.py','test_history_archive*.py','test_binance_backfill_fetcher.py']
files = sorted({str(p) for pattern in patterns for p in Path('backend/tests').glob(pattern)})
if __name__ == '__main__':
    raise SystemExit(pytest.main(['-q',*files,'--junitxml=output/cache-owner-audit-126-20261112/tests.xml']))
