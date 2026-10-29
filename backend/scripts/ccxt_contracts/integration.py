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
    import pytest

    patterns = (
        "test_ccxt_*.py", "test_history_archive_*.py", "test_backfill_coordinator.py",
        "test_backfill_rate_limit.py", "test_bar_basis_migration.py", "test_calendar_basis.py",
        "test_catalog_worker.py", "test_exchange_registry_plugins.py", "test_fixed_anchor.py",
        "test_ingestion_health_observer.py", "test_ingestion_session_types.py",
        "test_interval_resolution.py", "test_kline_series_identity.py", "test_kline_source_journal.py",
        "test_okx_utc_protocol.py", "test_plugin_provider_v2.py", "test_proxy_pool*.py",
        "test_public_admission.py", "test_public_transport_loopback.py", "test_source_revision_pipeline.py",
        "test_transport_http_rate_limit_metadata.py", "test_pyne_removal.py",
    )
    files = sorted({str(path) for pattern in patterns for path in (backend / "tests").glob(pattern)})
    return pytest.main(["-q", *files, *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
