"""Backend test modules that no other CI list runs, in the stages backend-tests.yml runs them.

Run from any directory with the workflow's Python:

    python backend/scripts/ci_backend_tests.py <stage> [pytest options]

Other lists already run about 390 modules: the .github/workflows files,
packages/candlescope-plugin-pine-compat/scripts/qualify_host_contracts.py and
backend/scripts/ccxt_contracts/integration.py. A module belongs here only when
none of them runs it. Every listed file must exist, so a renamed module fails
the job instead of silently leaving CI.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

STAGES = {
    # Replay broker, ledger and order money paths (#577 / #572).
    "replay-core": (
        "test_replay_broker_determinism.py", "test_replay_ledger.py", "test_replay_orders.py",
        "test_replay_order_workflows.py",
    ),
    # Every other test_replay_*.py that no other list runs, except *_benchmark.py timing runs.
    # test_replay_tape_projection*.py check the frontend parser through tsx: the job installs
    # frontend/node_modules first.
    "replay": (
        "test_replay_actor.py", "test_replay_architecture.py", "test_replay_bar_builder.py",
        "test_replay_bar_dataset.py", "test_replay_bar_source.py",
        "test_replay_blind_epoch.py", "test_replay_canonical_encoder.py",
        "test_replay_catalog_shutdown.py", "test_replay_checkpoint_delta.py",
        "test_replay_checkpoints.py", "test_replay_clock.py", "test_replay_commands.py",
        "test_replay_dependency_boundaries.py", "test_replay_determinism.py",
        "test_replay_drawing_rejections.py",
        "test_replay_drawing_wire_contract.py", "test_replay_events.py", "test_replay_execution_bar.py",
        "test_replay_execution_tape.py", "test_replay_fork_market_catalog.py",
        "test_replay_hedge_acceptance_matrix.py",
        "test_replay_hedge_dormant_account_inputs.py", "test_replay_hedge_hub_summary.py",
        "test_replay_hedge_legacy_summary.py", "test_replay_hedge_multitrack_review_fork.py",
        "test_replay_hedge_phase0_contract.py", "test_replay_hedge_phase0_inventory.py",
        "test_replay_hedge_phase1_contract.py", "test_replay_hedge_phase2_margin.py",
        "test_replay_hedge_phase3_inputs.py", "test_replay_hedge_phase4_accounting.py",
        "test_replay_hedge_tape_cohort_batch.py", "test_replay_hedge_timeline.py",
        "test_replay_hedge_track_readmission.py", "test_replay_hedge_wave_commit.py",
        "test_replay_history_discovery.py", "test_replay_history_publish_cas.py",
        "test_replay_hotpath_history.py", "test_replay_idle_checkpoint.py",
        "test_replay_indexed_interval.py", "test_replay_indexed_tape_context.py",
        "test_replay_indicator_prefix_archive.py", "test_replay_indicator_prefix_budget.py",
        "test_replay_interval_curve.py", "test_replay_interval_risk_search.py",
        "test_replay_market_halts.py", "test_replay_market_time_bounds.py",
        "test_replay_multi_phase.py", "test_replay_multitrack_batch.py",
        "test_replay_official_history_origin.py", "test_replay_p2_training_results.py",
        "test_replay_phase_projection.py", "test_replay_portfolio_batch.py",
        "test_replay_portfolio_export.py", "test_replay_preparation_work.py",
        "test_replay_prepared_cache.py", "test_replay_prepared_controls_and_prices.py",
        "test_replay_prepared_records.py", "test_replay_prepared_tape.py",
        "test_replay_progressive_actor.py", "test_replay_progressive_service.py",
        "test_replay_quality_gates.py", "test_replay_recorded_interval.py",
        "test_replay_remaining_hotpath.py", "test_replay_report.py",
        "test_replay_review_account_summary.py", "test_replay_review_budget_indexes.py",
        "test_replay_review_command_boundary.py", "test_replay_review_lifecycle_clock.py",
        "test_replay_service.py", "test_replay_shared_market_index.py",
        "test_replay_shared_snapshot.py", "test_replay_shared_training.py",
        "test_replay_smoke_fixture.py", "test_replay_snapshot_encoding.py",
        "test_replay_source_chain.py", "test_replay_startup_capacity.py",
        "test_replay_store.py", "test_replay_tape_phases.py", "test_replay_tape_projection.py",
        "test_replay_tape_projection_incremental.py", "test_replay_tape_projection_pages.py",
        "test_replay_terminal_cohort.py", "test_replay_track_admission_rollback.py",
        "test_replay_trade_audit.py", "test_replay_trade_determinism.py",
        "test_replay_trade_reader.py", "test_replay_trade_source.py",
        "test_replay_trade_summary.py", "test_replay_training_stream_delta.py",
        "test_replay_v2_contracts.py", "test_replay_v2_run_centric.py",
        "test_replay_v2_training_agg_hedge_isolated_user_journey.py",
        "test_replay_v2_training_api.py", "test_replay_v2_training_hedge_phase7.py",
        "test_replay_v2_training_phase10.py", "test_replay_v2_training_phase11.py",
        "test_replay_v2_training_phase12.py", "test_replay_v2_training_phase13.py",
        "test_replay_v2_training_phase14.py", "test_replay_v2_training_phase15.py",
        "test_replay_v2_training_phase16.py", "test_replay_v2_training_phase17.py",
        "test_replay_v2_training_phase18.py", "test_replay_v2_training_phase3.py",
        "test_replay_v2_training_phase4.py", "test_replay_v2_training_phase5.py",
        "test_replay_v2_training_phase6.py", "test_replay_v2_training_phase7.py",
        "test_replay_v2_training_phase8.py", "test_replay_v2_training_phase9.py",
        "test_replay_v2_training_source_event_dense.py", "test_replay_worker_isolation.py",
    ),
    # Indicator calculation, results and warmup, starting with the range batch (#448).
    # Left out: test_indicator_calculation_owner.py drives the compiled Pine engine
    # (candlescope-plugin-pine-compat), which only pine-host-contracts builds.
    "indicators": (
        "test_indicator_range_batch.py", "test_atr_preview_warmup.py",
        "test_boll_preview_warmup.py", "test_ema_preview_warmup.py",
        "test_indicator_calculation_registry.py", "test_indicator_compute_batch.py",
        "test_indicator_data_manager_bridge.py", "test_indicator_finite_windows.py",
        "test_indicator_plugin_serialization_parity.py",
        "test_indicator_range_result_service.py", "test_indicator_resume.py",
        "test_indicator_runtime_service.py", "test_indicator_series_revision.py",
        "test_indicator_sidecar_ws_regressions.py", "test_indicator_ws_resume.py",
        "test_ma_preview_warmup.py", "test_macd_preview_warmup.py",
        "test_related_warmup_scheduler.py", "test_rsi_preview_warmup.py",
        "test_script_batch_input_scope.py",
    ),
    # Data engine: history, backfill, catalogs, ingestion, preparation, order books and trades.
    # Left out: test_generic_native_rows.py skips itself unless backend/native is built
    # (setup_native.py), so it would run no case here.
    "data": (
        "test_append_batch_hub.py", "test_backfill_component_boundaries.py",
        "test_backfill_diagnostics.py", "test_backfill_dispatch_context.py",
        "test_backfill_event_audience.py",
        "test_backfill_gap_detector.py", "test_backfill_history_availability.py",
        "test_backfill_planned_coverage.py",
        "test_backfill_reconciler.py", "test_backfill_storage_availability.py",
        "test_bar_cache_history_capacity.py", "test_bar_cache_read_tokens.py",
        "test_binance_full_depth_contract.py", "test_binance_native_calendar.py",
        "test_binance_partial_depth_contract.py", "test_cache_behavior_decay.py",
        "test_cache_conflict_repairs.py",
        "test_calendar_gap_integration.py", "test_catalog_contract_adapters.py",
        "test_catalog_contract_rules.py", "test_catalog_metadata_retention.py",
        "test_checkpoint_json_reuse.py", "test_closed_bar_history_boundary.py",
        "test_cold_path_pure_shortcuts.py",
        "test_configure_replay_trade_history.py", "test_custom_aggregate_blocks.py",
        "test_custom_interval_listing_boundary.py", "test_custom_interval_phase1.py",
        "test_custom_materialization_ownership.py", "test_daily_open.py",
        "test_data_manager_domain_facades.py", "test_data_manager_gap_suppression.py",
        "test_dependent_invalidation_work.py", "test_depth_queue.py",
        "test_exchange_capabilities_v2.py", "test_exchange_plugin_contracts.py",
        "test_exchange_products.py", "test_exchange_support.py", "test_exchanges_api.py",
        "test_flat_trade_records.py", "test_full_order_book_api.py",
        "test_full_order_book_data_manager.py", "test_full_order_book_runtime.py",
        "test_full_order_book_stream.py", "test_gap_audit_series.py",
        "test_gap_ledger_reconciliation_session_races.py",
        "test_history_boundary_repository.py", "test_history_planner.py",
        "test_history_policy_integration.py", "test_ingestion_delivery.py",
        "test_ingestion_normalizers.py", "test_interval_routing_phase3.py",
        "test_interval_semantics_phase3.py", "test_interval_work_plan.py",
        "test_kline_query_projection.py", "test_kline_repair.py", "test_liquidation_api.py",
        "test_liquidation_data_manager.py", "test_liquidation_runtime.py",
        "test_liquidation_storage.py", "test_liquidation_stream.py",
        "test_manual_gap_audit.py", "test_manual_history_api.py",
        "test_manual_history_planner.py", "test_manual_history_repository.py",
        "test_manual_history_runtime.py", "test_manual_history_service.py",
        "test_market_data_catalog.py", "test_market_data_service.py",
        "test_market_dataset_architecture.py", "test_market_event_hub.py",
        "test_market_random.py", "test_market_source_capture_switch.py",
        "test_market_storage_bootstrap.py", "test_market_stream_api.py",
        "test_market_stream_models.py", "test_multi_chart_capacity.py",
        "test_multi_chart_hard_limits.py", "test_multi_chart_upstream_shards.py",
        "test_multi_market.py", "test_official_history_binding.py",
        "test_official_trade_history.py", "test_okx_backfill_fetcher.py",
        "test_okx_capture.py", "test_order_book_api.py", "test_order_book_auto.py",
        "test_order_book_data_manager.py", "test_order_book_runtime.py",
        "test_order_book_stream.py", "test_patch_binance_replay_history_rest.py",
        "test_preparation_async_boundaries.py", "test_preparation_cache_writes.py",
        "test_preparation_dependencies.py", "test_preparation_first_launch.py",
        "test_preparation_market_history.py", "test_preparation_prefetch.py",
        "test_preparation_publication_space.py", "test_preparation_session_objects.py",
        "test_preparation_storage_inventory.py", "test_preparation_waiting.py",
        "test_price_subscription_services.py", "test_progressive_preparation.py",
        "test_query_engine_paths.py", "test_resting_trade_filter.py", "test_sampled_book.py",
        "test_snapshot_replay_klines.py", "test_storage_gap_scan.py", "test_stream_api.py",
        "test_stream_transport_close.py", "test_symbol_catalog_contracts.py",
        "test_symbol_catalog_refresh.py", "test_symbol_discovery.py",
        "test_symbol_normalization.py", "test_trade_candle_sources.py",
        "test_trade_candles.py", "test_trade_history_round3.py",
        "test_trade_snapshot_cache.py", "test_trade_tape.py", "test_transport_ws_urls.py",
        "test_twelve_data_provider.py", "test_upstream_availability.py",
    ),
}


def stage_files(backend: Path, stage: str) -> list[str]:
    names = STAGES[stage]
    if len(set(names)) != len(names):
        raise ValueError(f"{stage} lists a module twice")
    files = [backend / "tests" / name for name in names]
    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        raise FileNotFoundError(", ".join(missing))
    return [str(path) for path in files]


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in STAGES:
        print(f"usage: ci_backend_tests.py {'|'.join(STAGES)} [pytest options]", file=sys.stderr)
        return 2
    all_names = [name for names in STAGES.values() for name in names]
    if len(set(all_names)) != len(all_names):
        raise ValueError("a module is listed in two stages")
    backend = Path(__file__).resolve().parents[1]
    files = stage_files(backend, sys.argv[1])
    os.chdir(backend)
    sys.path.insert(0, str(backend))
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    import pytest

    return pytest.main(["-q", "-p", "pytest_asyncio.plugin", "-p", "anyio.pytest_plugin",
                        "-p", "pytest_timeout", "-p", "xdist.plugin", *files, *sys.argv[2:]])


if __name__ == "__main__":
    # Indicator and catalog tests start child processes that re-import __main__.
    raise SystemExit(main())
