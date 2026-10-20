"""Independent Pine decisions, allocation and account feedback per cost scenario."""
from copy import deepcopy
from decimal import Decimal
import time

from app.market_dataset.snapshot import sha256_hex
from app.simulation.cost_sensitivity import _clone_kernel, _scenario_wire
from app.simulation.dual_clock_kernel import DualClockSimulationKernel
from app.simulation.kernel import SimulationKernel

from .errors import BacktestError
from .pine_callbacks import ChartFillCallbacks
from .strategy.host_adapter import StrategyHostAdapter
from .strategy.pine_engine import PineEngineProvider
from .strategy.protocol import StrategyProviderSession, canonical_hash


def build_matrix(service, config, kernel, events, primary, *, provider, planner, market,
                 warmup, deadline, control, run_id, input_plan):
    context = deepcopy(input_plan)
    primary_policy = canonical_hash(planner.report())

    def evaluate(replay):
        from .service import _new_host_planner, _pine_account_view, _planning_context
        check_deadline(deadline)
        control()
        fresh = PineEngineProvider()
        session = StrategyProviderSession(fresh, run_id=run_id)
        # Cost scenarios keep an explicit per-step deadline even when their
        # parent run is already inside the supervised whole-run worker.
        adapter = StrategyHostAdapter(session, inline=False,
            step_timeout_s=service.settings.provider_step_timeout_ms / 1000)
        shadow_config = {**config, **{name: str(getattr(replay, name)) for name in
            ("slippage_bps", "taker_fee_bps", "maker_fee_bps", "participation_rate")},
            "latency_ms": replay.latency_ms, "latency_events": replay.latency_events}
        account_kernel = replay.execution if isinstance(replay, DualClockSimulationKernel) else replay
        source_kernel = kernel.execution if isinstance(kernel, DualClockSimulationKernel) else kernel
        # Preserve production evidence/curve modes when verifying the baseline.
        replay.scale_stream_decisions = kernel.scale_stream_decisions
        replay.equity_curve_mode = kernel.equity_curve_mode
        for name in ("equity_curve_mode", "_record_encoder", "_native_empty_hash", "_specialized_bar"):
            if hasattr(account_kernel, name) and hasattr(source_kernel, name):
                setattr(account_kernel, name, getattr(source_kernel, name))
        account_kernel.execution_reporter = service._execution_reporter(session)
        shadow_planner = _new_host_planner(shadow_config, execution_reporter=service._execution_reporter(session))
        observed = 0
        try:
            adapter.start(deepcopy(context))
            if fresh.identity() != provider.identity():
                raise BacktestError("IDENTITY_MUTATION", "Pine scenario runtime differs from the primary provider")
            shadow_planner.bind_kernel(replay)
            callbacks = None
            def features(bar):
                return service._observation_features(fresh, bar=bar, trade=None)
            historical_callbacks = None
            if config.get("pine_bar_path_contract"):
                from .pine_chart_bar import ChartHistoricalBarCallbacks
                historical_callbacks = ChartHistoricalBarCallbacks(session, adapter, shadow_planner, replay,
                    market=market, warmup=warmup, features=features, control=control, deadline=deadline)
            elif config.get("pine_fill_callbacks"):
                callbacks = ChartFillCallbacks(session, adapter, shadow_planner, replay,
                    market=market, warmup=warmup, features=features, control=control, deadline=deadline)
            closing = None
            if config.get("pine_process_on_close") and historical_callbacks is None:
                from .pine_closing import ChartClosingTicks
                closing = ChartClosingTicks(replay, callbacks)

            def strategy(_visible, event):
                nonlocal observed
                check_deadline(deadline)
                if observed % 256 == 0:
                    control()
                index = event.sequence - 1 if isinstance(replay, DualClockSimulationKernel) else observed
                observed += 1
                if historical_callbacks is not None:
                    return historical_callbacks.observe(event)
                if callbacks is not None:
                    return callbacks.observe(event, confirmed=True)
                bar = dict(event.payload)
                service._assert_frame_inputs(fresh, bar=bar, trade=None)
                output = adapter.observe(sequence=event.sequence, event_time_ms=event.event_time_ms,
                    watermark_ms=event.event_time_ms, phase="WARMUP" if index < warmup else "EVALUATION",
                    market=dict(market), bar=bar, features=features(bar), account_view=_pine_account_view(replay))
                return shadow_planner.plan(output,
                    context=None if shadow_planner.config is None else _planning_context(account_kernel, event))

            result = replay.run(events, strategy, warmup_events=0, finalize=True,
                **({"fill_callback": callbacks.on_fill} if callbacks is not None else {}),
                **({"fill_callback": historical_callbacks.on_fill} if historical_callbacks is not None else {}),
                **({"close_callback": closing.process} if closing is not None else {}))
            service._assert_provider_state_budget(session.snapshot())
            check_deadline(deadline)
            control()
            return result, {"hash": canonical_hash(shadow_planner.report()),
                "rejection_count": len(shadow_planner.rejections)}, fresh.report_metadata()
        finally:
            try:
                session.close()
            finally:
                adapter.close()
                account_kernel.execution_reporter = None
                account_kernel.order_policy = None
                account_kernel.market_observer = None

    baseline, baseline_policy, metadata = evaluate(_clone_kernel(kernel))
    hashes = ("decision_hash", "fill_hash", "ledger_hash", "report_hash")
    if (any(getattr(primary, key) != getattr(baseline, key) for key in hashes)
            or primary.orders != baseline.orders or primary.equity_curve != baseline.equity_curve
            or baseline_policy["hash"] != primary_policy):
        raise BacktestError("PINE_SENSITIVITY_BASELINE_MISMATCH", "Independent Pine baseline differs from the primary Host execution")

    rate = kernel.participation_rate
    def assumptions(multiplier="1", latency=False, participation=rate):
        return {"fee_multiplier": multiplier, "slippage_multiplier": multiplier,
            "latency_ms_delta": 100 if latency else 0, "latency_events_delta": 1 if latency else 0,
            "participation_rate": None if participation is None else str(participation)}

    scenarios = [summarize("BASELINE", assumptions(), baseline, baseline_policy, metadata)]
    for label, multiplier in (("COSTS_PLUS_25_PERCENT", Decimal("1.25")), ("COSTS_PLUS_50_PERCENT", Decimal("1.5"))):
        replay = _clone_kernel(kernel, slippage_bps=kernel.slippage_bps * multiplier,
            taker_fee_bps=kernel.taker_fee_bps * multiplier, maker_fee_bps=kernel.maker_fee_bps * multiplier)
        scenarios.append(summarize(label, assumptions(str(multiplier)), *evaluate(replay)))
    if isinstance(kernel, SimulationKernel):
        scenarios.append(summarize("LATENCY_PLUS_ONE_TIER", assumptions(), baseline, baseline_policy, metadata,
            status="NOT_APPLICABLE_BAR_CLOCK"))
    else:
        replay = _clone_kernel(kernel, latency_ms=kernel.latency_ms + 100, latency_events=kernel.latency_events + 1)
        scenarios.append(summarize("LATENCY_PLUS_ONE_TIER", assumptions(latency=True), *evaluate(replay)))
    if rate is None:
        scenarios.append(summarize("PARTICIPATION_DOWN_ONE_TIER", assumptions(), baseline, baseline_policy, metadata,
            status="NOT_APPLICABLE_OHLC_PATH_NO_TAPE_CAPACITY"))
    else:
        replay = _clone_kernel(kernel, participation_rate=rate / 2)
        scenarios.append(summarize("PARTICIPATION_DOWN_ONE_TIER", assumptions(participation=rate / 2), *evaluate(replay)))
    payload = {"schemaVersion": "candlescope.cost-sensitivity/1", "status": "COMPLETED",
        "purpose": "ROBUSTNESS_CHECK_NOT_PARAMETER_TUNING", "decision_source": "INDEPENDENT_PINE_HOST_REEXECUTION",
        "included_in_primary_config_hash": False, "baseline_reexecution_verified": True, "scenarios": scenarios}
    return {**payload, "matrix_hash": "sha256:" + sha256_hex(payload)}


def summarize(name, assumptions, result, policy, metadata, *, status="COMPLETED"):
    wire = _scenario_wire(name, assumptions, result)
    wire.pop("scenario_hash")
    wire["status"] = status
    wire["hashes"].update(decision=result.decision_hash, policy=policy["hash"])
    wire["metrics"].update(rejection_count=len(result.rejected) + policy["rejection_count"],
        ending_position=str(result.ledger.get("account", {}).get("position_qty", "0")))
    wire["pine_execution"] = metadata["pineExecution"]
    return {**wire, "scenario_hash": "sha256:" + sha256_hex(wire)}


def check_deadline(deadline):
    if time.monotonic() >= deadline:
        raise BacktestError("BUDGET_EXCEEDED", "Pine cost scenarios exceeded the run time ceiling")
