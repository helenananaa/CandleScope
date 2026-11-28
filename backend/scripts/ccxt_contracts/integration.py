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
        "test_backfill_rate_limit.py", "test_binance_backfill_fetcher.py",
        "test_data_manager_warm_start_bridge.py", "test_backfill_interest_priority.py",
        "test_bar_basis_migration.py", "test_pre_migration_copy.py", "test_calendar_basis.py",
        "test_catalog_worker.py", "test_exchange_registry_plugins.py", "test_fixed_anchor.py",
        "test_symbol_discovery.py",
        "test_ingestion_health_observer.py", "test_ingestion_session_types.py",
        "test_interval_resolution.py", "test_interval_admission_contract.py",
        "test_oi_local_history.py",
        "test_okx_history_range_fence.py", "test_native_history_range_fence.py",
        "test_routed_history_range_views.py", "test_futures_history_live_writes.py",
        "test_derived_history_range_fence.py", "test_second_empty_coverage_fences.py",
        "test_data_engine_phase1_boundaries.py",
        "test_kline_series_identity.py", "test_kline_source_journal.py", "test_kline_batch*.py",
        "test_okx_utc_protocol.py", "test_plugin_provider_v2.py", "test_proxy_pool*.py",
        "test_public_admission.py", "test_public_transport_loopback.py", "test_source_revision_pipeline.py",
        "test_transport_http_rate_limit_metadata.py", "test_pyne_removal.py",
        "test_bar_delivery_*.py", "test_revision_delivery_recovery.py",
        "test_kline_revision_contract.py", "test_query_cache_fencing.py", "test_cache_metadata_budget.py",
        "test_indicator_api.py", "test_indicator_runtime_transport_routing.py",
        "test_*subscription_continuity.py", "test_recovery_*.py", "test_consumer_recovery.py",
        "test_custom_history_streaming.py", "test_materialized_history_probe.py",
        "test_history_revision_admission.py", "test_aggregation_core.py",
        "test_trade_preparation.py", "test_replay_trade_import.py", "test_trade_flow_api.py",
        "test_shared_aggregation_blocks.py", "test_shared_blocks_integration.py",
        "test_history_block_reader.py",
        "test_history_prefix*.py",
        "test_history_fetch_stream*.py",
        "test_history_cover_plan.py", "test_mixed_history_reader.py", "test_default_mixed_history_query.py",
        "test_mixed_history_precedence.py",
        "test_history_cover_batch.py", "test_backfill_canonical_planning_reads.py",
        "test_canonical_history_stream.py",
        "test_mixed_backfill_*.py",
        "test_component_incremental.py", "test_shared_component_input.py", "test_realtime_target_lifecycle.py",
        "test_realtime_handoff_accounting.py", "test_realtime_eviction_handoff.py",
        "test_preview_update_requirements.py", "test_event_bus_routing_index.py",
        "test_deferred_component_preview*.py",
        "test_closed_component_retention*.py",
        "test_forming_component_retention*.py",
        "test_source_window_recovery*.py",
        "test_component_payload_accounting.py", "test_component_index_memory.py", "test_readonly_payload_weight.py",
        "test_interval_policy_consistency.py", "test_bar_aggregator_contracts.py",
        "test_kline_order_flow_metrics.py", "test_history_calendar.py",
        # ADR-BACKTEST-015 P0 financial oracles (Pine paths run in pine-host-contracts).
        "test_strategy_run_oracles.py", "test_run_result.py",
        # ADR-BACKTEST-015 P2: one run facade over every run family.
        "test_strategy_runs.py", "test_strategy_runs_forward.py",
        # ADR-BACKTEST-015 P3: strategy drafts and versions in the backend.
        "test_strategy_drafts.py", "test_strategy_versions.py", "test_strategy_references.py",
        # ADR-BACKTEST-015 P4: FOLLOW equals FIXED; chart FOLLOW runs fed by the DataManager.
        "test_follow_session.py", "test_strategy_follows.py", "test_strategy_experiments.py", "test_strategy_run_derive.py", "test_strategy_experiment_robustness.py",
        # ADR O2: Pine FOLLOW keeps the results of the 8 most recently active follows.
        "test_native_follow_results.py",
        "test_execution_data_market.py",
        # Replay: no future data before reveal (launch non-negotiable) and revealed indicator columns.
        "test_replay_no_lookahead.py", "test_replay_indexed_indicator_closes.py",
        "test_replay_market_indicator_columns.py", "test_replay_indicator_market_columns.py",
        "test_replay_indicator_http.py",
        # Replay fast paths match the scalar / per-event reference; wire contracts and stream resync.
        # test_replay_hedge_tape_interval.py needs minutes per case: ccxt-integration.yml runs it as its own job.
        "test_replay_interval_advance.py", "test_replay_tape_interval.py",
        "test_replay_advance_atomic_finish.py", "test_replay_bar_parity.py", "test_replay_trade_bar_parity.py",
        "test_replay_contracts.py", "test_replay_stream.py", "test_replay_workspace_drawings.py",
        # 1s history, replay catalog and local import.
        "test_second_history_lifecycle.py", "test_sparse_source_continuity.py", "test_replay_catalog.py",
        "test_local_data_api.py", "test_replay_imported_multimarket.py",
        # GC, retention and cache protection; derived stores follow a moved or copied data folder.
        "test_profile_relocation.py",
        "test_bar_cache_protection.py", "test_data_manager_gc.py", "test_gc_execution_safety.py",
        "test_gc_policy.py", "test_gc_settings_validation.py", "test_storage_retention_gc.py",
        "test_manual_history_gc_protection.py",
        # Trade flow, order book, liquidation and kline quality.
        "test_trade_flow_engine.py", "test_trade_flow_service.py", "test_trade_flow_storage.py",
        "test_trade_flow_stream.py", "test_trade_flow_runtime.py", "test_trade_flow_data_manager.py",
        "test_trade_tape_service.py", "test_full_order_book_engine.py", "test_full_order_book_service.py",
        "test_order_book_engine.py", "test_order_book_service.py", "test_liquidation_engine.py",
        "test_liquidation_service.py", "test_kline_quality_contract.py",
        # Raw trade archive retention, OI / funding coverage and exchange capabilities.
        "test_raw_trade_retention_lock.py", "test_replay_trade_service.py", "test_replay_remote_trade_archive.py",
        "test_oi_history_lifecycle.py", "test_exchange_history_availability.py", "test_gap_ledger.py",
        "test_exchange_capability_v2.py",
        # Alerts on the shared numeric indicator subscription (the delivery soak test stays out).
        "test_alerts_api.py", "test_alerts_definition_cursor.py", "test_alerts_evaluator.py",
        "test_alerts_hot_path.py", "test_alerts_indicator_fields.py", "test_alerts_lifecycle_races.py",
        "test_alerts_notifications.py", "test_alerts_numeric_integration.py", "test_alerts_outbox.py",
        "test_alerts_runtime.py", "test_numeric_indicator_queries.py", "test_numeric_subscription_shutdown.py",
        # Indicator value contract, script close snapshots and indicator routes.
        "test_indicator_seed_consistency.py", "test_script_close_event_snapshot.py",
        "test_indicator_runtime_routes.py", "test_indicator_history_transport_independence.py",
        # Synthetic series and chart inputs.
        "test_synthetic_series.py", "test_synthetic_api.py", "test_synthetic_pinned.py",
        "test_chart_indicator_input.py", "test_chart_strategy_signals.py",
        # Strategy results in replay reveal only the revealed prefix (Pine-native replay runs in pine-host-contracts).
        "test_local_bar_result_replay.py", "test_native_replay_views.py", "test_native_replay_origin.py",
        # Local imports: bars, user market trades and manual replay imports.
        "test_local_data_service.py", "test_local_data_jobs.py", "test_user_market_trades.py",
        "test_replay_imported_market_trades.py", "test_market_dataset_local_bar.py", "test_manual_replay_import.py",
        # External model interface.
        "test_external_provider_*.py", "test_external_model_adapters.py",
        # Simulation and backtest layering, and the backtest core.
        "test_simulation_architecture.py", "test_backtest_architecture.py", "test_backtest_accounting.py",
        "test_backtest_determinism.py", "test_backtest_execution.py", "test_simulation_kernel.py",
        # Practice HEDGE money and migration, multi-chart replay finances, restart and shutdown.
        "test_trading_practice_hedge.py", "test_trading_state_shutdown.py", "test_replay_multi_interval.py",
        "test_replay_multi_interval_service.py", "test_replay_recovery.py", "test_replay_shutdown.py",
        # ADR-DATA-002 D4: host credential vault, data-source keys and the Twelve Data provider that reads them.
        "test_host_credential_vault.py", "test_data_source_credentials.py", "test_twelve_data_provider.py",
    )
    files = sorted({str(path) for pattern in patterns for path in (backend / "tests").glob(pattern)})
    return pytest.main(["-q", "-p", "pytest_asyncio.plugin", "-p", "anyio.pytest_plugin",
                        "-p", "pytest_timeout", *files, *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
