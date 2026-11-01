"""Run the composed public-market contracts against the required pinned fork.

Run from backend with the integration environment's Python. Extra pytest options
are forwarded, for example --junitxml=../output/ccxt-integration/backend.xml.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys


def main() -> int:
    backend = Path(__file__).resolve().parents[2]
    os.chdir(backend)
    sys.path.insert(0, str(backend))
    os.environ["CANDLESCOPE_REQUIRE_CCXT_FORK"] = "1"
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    import pytest

    patterns = (
        "test_ccxt_*.py", "test_history_archive_*.py", "test_backfill_coordinator.py",
        "test_backfill_rate_limit.py", "test_bar_basis_migration.py", "test_calendar_basis.py",
        "test_catalog_worker.py", "test_exchange_registry_plugins.py", "test_fixed_anchor.py",
        "test_ingestion_health_observer.py", "test_ingestion_session_types.py",
        "test_interval_resolution.py", "test_interval_admission_contract.py",
        "test_data_engine_phase1_boundaries.py",
        "test_kline_series_identity.py", "test_kline_source_journal.py",
        "test_okx_utc_protocol.py", "test_plugin_provider_v2.py", "test_proxy_pool*.py",
        "test_public_admission.py", "test_public_transport_loopback.py", "test_source_revision_pipeline.py",
        "test_transport_http_rate_limit_metadata.py", "test_pyne_removal.py",
        "test_bar_delivery_*.py", "test_revision_delivery_recovery.py",
        "test_kline_revision_contract.py", "test_query_cache_fencing.py",
        "test_indicator_api.py", "test_indicator_runtime_transport_routing.py",
        "test_*subscription_continuity.py", "test_recovery_*.py", "test_consumer_recovery.py",
        "test_custom_history_streaming.py", "test_materialized_history_probe.py",
        "test_history_revision_admission.py", "test_aggregation_core.py",
        "test_shared_aggregation_blocks.py", "test_shared_blocks_integration.py",
        "test_history_block_reader.py",
        "test_interval_policy_consistency.py", "test_bar_aggregator_contracts.py",
        "test_kline_order_flow_metrics.py", "test_history_calendar.py",
    )
    files = sorted({str(path) for pattern in patterns for path in (backend / "tests").glob(pattern)})
    return pytest.main(["-q", "-p", "pytest_asyncio.plugin", "-p", "anyio.pytest_plugin",
                        "-p", "pytest_timeout", *files, *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
