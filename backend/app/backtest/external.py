"""CandleScope-owned BAR matching with actual Pine/Pyne account feedback.

V2 supports price orders, brackets and separate bar/print execution clocks.
No native fills are accepted. The kernel remains the only accounting authority.
"""
from __future__ import annotations

from dataclasses import asdict
from copy import deepcopy
from decimal import Decimal
import json
import time
import hashlib
from pathlib import Path

from app.market_dataset.snapshot import MarketEvent
from app.simulation.kernel import SimulationKernel
from app.data_engine.interval_policy import parse_interval_spec
from .errors import BacktestError
from .external_orders import ExternalOrders
from .external_report import closed_trades
from .external_support import persistent_evaluator


def host_identity():
    import app.simulation.kernel as kernel_module
    files = [Path(__file__), Path(__file__).with_name("native_session.py"), Path(__file__).with_name("external_orders.py"), Path(__file__).with_name("external_report.py"), Path(__file__).with_name("external_market.py"), Path(__file__).with_name("external_feedback.py"), Path(__file__).with_name("external_incremental.py"), Path(__file__).with_name("external_replay.py"), *sorted(Path(kernel_module.__file__).parent.rglob("*.py"))]
    checksum = hashlib.sha256()
    files.extend(Path(__file__).with_name(name) for name in ("native_replay.py","native_replay_storage.py","native_replay_views.py","native_checkpoint.py"))
    files.append(Path(__file__).with_name("pine_entry_risk.py"))
    files.extend(Path(__file__).with_name(name) for name in ("pine_risk_state.py", "pine_risk_stops.py"))
    files.append(Path(__file__).with_name("pine_workbench.py"))
    files.append(Path(__file__).with_name("pine_sizing.py"))
    files.append(Path(__file__).with_name("pine_order_metadata.py"))
    files.append(Path(__file__).with_name("external_support.py"))
    files.append(Path(__file__).with_name("pine_bar_clock.py"))
    files.append(Path(__file__).with_name("pine_workbench_v2.py"))
    files.append(Path(__file__).with_name("native_contracts.py"))
    files.append(Path(__file__).with_name("pine_contract_metadata.py"))
    files.append(Path(__file__).with_name("pine_request_updates.py"))
    files.append(Path(__file__).with_name("pine_print_account.py"))
    files.append(Path(__file__).with_name("workbench_sensitivity.py"))
    files.extend(Path(__file__).with_name(name) for name in ("pine_stream.py","pine_history_tick_clock.py","pine_history_tick_execution.py","pine_print_tick_execution.py","pine_event_requests.py"))
    # This shared builder also runs in the Host when freezing/restoring sources.
    # Its installed bytes must be bound independently of the worker SDK hash.
    try:
        from candlescope_plugin_sdk import event_requests
    except ImportError:
        pass  # Older SDKs retain ordinary execution without event capability.
    else:
        files.append(Path(event_requests.__file__))
    for path in files:
        checksum.update(path.name.encode())
        checksum.update(path.read_bytes())
    return {"contract": "external-broker/1", "host_model": "PYNE_FIXED_HISTORY_V12_CLOSED_TRADES", "code_sha256": checksum.hexdigest()}


def account_feedback_profit(account, initial_balance):
    # Buying an asset spends cash, but is not a realized trading loss. This
    # formula also preserves the legacy derivative account's net-profit value.
    return account.equity() - initial_balance - account.unrealized()


def visible_contexts(wire, boundary_ms):
    """Only fully closed auxiliary bars may cross the host execution boundary."""
    contexts = wire.get("contexts", [])
    intervals = wire.get("context_intervals", [])
    if len(contexts) != len(intervals):
        raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "requested data interval metadata missing")
    visible = []
    for context, interval in zip(contexts, intervals, strict=True):
        spec = parse_interval_spec(interval)
        visible.append({**context, "bars": [bar for bar in context["bars"]
                        if spec.next_ms(bar["time"] * 1000) <= boundary_ms]})
    return visible


def resolve_external(language):
    from .native import resolve_plugin
    plugin = resolve_plugin(language)
    plugin["command"][-1] = plugin["command"][-1].replace(".native_strategy", ".external_strategy")
    return plugin


def run_external_host(plugin, wire, runner, cancelled, **options):
    from .native import invoke
    from .native_session import SessionWorker
    options.setdefault("deadline", time.monotonic() + 120)
    options.setdefault("_scenario_runner", runner)
    if wire.get("pine_history_tick_contract") or wire.get("pine_print_tick_contract"):
        if wire.get("pine_print_tick_contract"):
            from .pine_print_tick_execution import open_stream
        else:
            from .pine_history_tick_execution import open_stream
        stream=open_stream(plugin,wire,cancelled,options["deadline"],resume=options.get("resume"))
        try:
            return _run_external_host(plugin,wire,runner,cancelled,_pine_stream=stream,**options)
        finally:
            stream.close()
    if runner is invoke and persistent_evaluator(wire["identity"]):
        worker = SessionWorker(plugin, wire, cancelled, evaluator=True)
        try:
            def evaluate(_plugin, payload, **kwargs):
                return worker.request(payload, **kwargs)
            if wire["identity"].get("adapter") == "pyne-external/5":
                from .external_incremental import IncrementalEvaluator
                evaluate = IncrementalEvaluator(worker, len(wire["bars"]))
            return _run_external_host(plugin, wire, evaluate, cancelled, **options)
        finally:
            worker.close()
    return _run_external_host(plugin, wire, runner, cancelled, **options)


def _run_external_host(plugin, wire, runner, cancelled, *, resume=None, target=None,
                       deadline=None, _cost_scenario=False, _scenario_runner=None, _pine_stream=None,
                       _discovery_only=False, _consume_resume=False, _capture_owned=False):
    if wire.get("host_runtime_identity") != host_identity():
        raise BacktestError("NATIVE_IDENTITY_MISMATCH", "host matching code changed after submission")
    from .workbench_sensitivity import validate_contract, check_control
    validate_contract(wire)
    deadline = time.monotonic() + 120 if deadline is None else deadline
    scenario_runner = runner if _scenario_runner is None else _scenario_runner
    source_runner = runner
    def bounded_runner(plugin, request, **kwargs):
        check_control(cancelled, deadline)
        kwargs["timeout"] = min(kwargs.get("timeout", 120), deadline - time.monotonic())
        return source_runner(plugin, request, **kwargs)
    runner = bounded_runner
    settings = wire["host_settings"]
    fidelity = wire.get("execution_fidelity", "BAR_APPROX")
    from app.simulation.trade_kernel import TradeSimulationKernel
    from app.simulation.book_kernel import BookAssistedKernel
    from app.simulation.depth_kernel import DepthQueueKernel
    from app.simulation.sampled_book_kernel import SampledBookKernel
    kernel_type = {"BAR_APPROX":SimulationKernel,"BOOK_ASSISTED":BookAssistedKernel,
                   "TRADE_TAPE":TradeSimulationKernel,"BOOK_DEPTH":DepthQueueKernel,"BOOK_SAMPLED":SampledBookKernel}[fidelity]
    if wire.get("pine_bar_path_contract"):
        from app.simulation.pine_bar_kernel import PineBarKernel, CONTRACT as PATH_CONTRACT
        if (fidelity != "BAR_APPROX" or wire["pine_bar_path_contract"] != PATH_CONTRACT
                or not (wire.get("fill_recalculation") or wire.get("pine_history_tick_contract"))):
            raise BacktestError("EXTERNAL_UNSUPPORTED", "invalid Pine BAR path contract")
        kernel_type = PineBarKernel
        if wire.get("pine_v2_bar_contract"):
            from app.simulation.pine_v2_bar_kernel import PineV2BarKernel, CONTRACT as V2_CONTRACT
            if wire["pine_v2_bar_contract"] != V2_CONTRACT:
                raise BacktestError("EXTERNAL_UNSUPPORTED", "invalid Pine V2 BAR contract")
            kernel_type = PineV2BarKernel
    print_kwargs = {}
    if (wire.get("pine_v2_print_contract") and fidelity == "TRADE_TAPE"
            and wire["pine_v2_settings"].get("execution_model_revision") == "EXECUTION_REALISM_V2"):
        from app.simulation.execution_realism import TRADE_FILL_POLICY_V2
        print_kwargs["fill_policy"] = TRADE_FILL_POLICY_V2
    kernel = kernel_type(**print_kwargs, **({"process_orders_on_close": True} if issubclass(kernel_type, SimulationKernel) and wire.get("closing_ticks") else {}),
                              **({key: (Decimal(value) if key in {"leverage", "participation_rate"} and value is not None else value)
                                  for key, value in wire["pine_v2_settings"].items()
                                  if key != "bar_path_scenario" or not wire.get("pine_v2_print_contract")} if wire.get("pine_v2_bar_contract") or wire.get("pine_v2_print_contract") else {}),
                              account_model=wire.get("account_model", "LINEAR_PERP_ONE_WAY_V1"),
                              initial_balance=Decimal(str(settings["initial_balance"])),
                              slippage_bps=Decimal(str(settings["slippage_bps"])),
                              taker_fee_bps=Decimal(str(settings["taker_fee_bps"])))
    from .pine_contract_metadata import configure_legacy_account
    configure_legacy_account(kernel, wire)
    interval = parse_interval_spec(wire["interval"])
    capture=target is not None
    if _capture_owned and (not capture or _pine_stream is None or _discovery_only):
        raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "owned checkpoint requires a captured Pine replay")
    if _discovery_only and (capture or resume is not None or not _cost_scenario or _pine_stream is None):
        raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "window discovery requires a disposable fresh account")
    target=len(wire["bars"]) if target is None else target
    if type(target) is not int or not 1<=target<=len(wire["bars"]):
        raise BacktestError("NATIVE_REPLAY_RANGE","invalid external chart cursor")
    accounts,history,latest=[],[],{}
    orders = ExternalOrders(kernel, price_tick=settings.get("price_tick"),
                            fidelity="PINE_BAR_PATH" if wire.get("pine_bar_path_contract") else fidelity)
    orders.negotiate_metadata(wire.get("order_metadata_contract"))
    clock,last_request,cursor={},None,0
    if resume is not None:
        from .external_replay import validate_state
        validate_state(wire,resume)
        cursor=resume["cursor"]
        if cursor>target:
            raise BacktestError("NATIVE_REPLAY_RANGE","external restore cannot advance backward")
        kernel.restore(resume["kernel"])
        orders.restore(resume["orders"])
    from .pine_workbench import configure_risk, check_risk_response
    risk_stops = configure_risk(orders, wire, resume=resume)
    if resume is not None:
        accounts,history,latest=resume["accounts"],resume["history"],resume["latest"]
        clock,last_request=resume["clock"],resume["last_request"]
        # Rebuild only the evaluator transcript. Restored fills, fees, depth and
        # ownership stay in the Host kernel and must never be matched again.
        if _pine_stream is None:
            reproduced=runner(plugin,last_request,cancelled=cancelled,timeout=120)
            from .native_replay_storage import same_json
            if not same_json(reproduced,latest):
                raise BacktestError("EXTERNAL_NONCAUSAL_PREFIX","restored evaluator transcript changed")
        elif _consume_resume:
            # Only a job-owned checkpoint may be consumed. All identity,
            # transcript, kernel, allocation and risk restoration checks above
            # have finished; matching clocks take the job's mutable histories.
            clock={key:value for key,value in clock.items() if key not in {"stream","latest"}}
            accounts,history,latest=[],[],{}
            last_request=None
            resume.clear()

    def evaluate(plugin,request,**kwargs):
        nonlocal last_request
        last_request=request
        return runner(plugin,request,**kwargs)

    from .pine_request_updates import from_wire as requested_feed_from_wire, validate_replay as validate_requested_replay
    request_feed = requested_feed_from_wire(wire) if not (wire.get("fill_recalculation") or _pine_stream is not None) else None
    request_groups = deepcopy((last_request or {}).get("request_updates", [])) if request_feed is not None else []
    if request_feed is not None and resume is not None:
        validate_requested_replay(request_feed, clock.get("request_feed"), request_groups)

    def strategy(_window, event):
        nonlocal latest
        if cancelled.is_set():
            raise BacktestError("NATIVE_CANCELLED", "host matching cancelled")
        if time.monotonic() >= deadline:
            raise BacktestError("NATIVE_TIMEOUT", "host matching exceeded deadline")
        orders.feedback()
        account = kernel.account
        count = len(accounts) + 1
        accounts.append({"time": wire["bars"][count - 1]["time"], "position_size": float(account.position_qty),
                         "position_avg_price": None if account.entry_price is None else float(account.entry_price),
                         "equity": float(account.equity()), "initial_capital": float(kernel.initial_balance),
                         "netprofit": float(account_feedback_profit(account, kernel.initial_balance)), "openprofit": float(account.unrealized())})
        request = {**{key: value for key, value in wire.items() if key not in {"execution_events", "account_events", "account_provenance", "pine_v2_settings"}}, "bars": wire["bars"][:count], "accounts": accounts}
        if "execution_times" in wire:
            request["execution_times"] = wire["execution_times"][:count]
        boundary = interval.next_ms(wire["bars"][count - 1]["time"] * 1000)
        if request_feed is not None:
            request_groups.append(dict(observed_at_ms=boundary - 1, updates=request_feed.advance(boundary - 1)))
            request.update(contexts=request_feed.empty_contexts(), request_updates=request_groups)
        else:
            request["contexts"] = visible_contexts(wire, boundary)
        latest = evaluate(plugin, request, cancelled=cancelled, timeout=max(0.1, deadline - time.monotonic()))
        if request_feed is not None:
            clock["request_feed"] = request_feed.snapshot()
        if latest.get("contract") != "external-broker/1" or latest.get("identity") != wire["identity"] or latest.get("account_authority") != "candlescope" or latest.get("execution_mode") != "CANDLESCOPE":
            raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "external runtime returned the wrong account contract")
        if latest.get("raw_output", {}).get("strategy"):
            raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "native account output is forbidden")
        emitted = latest["intents"]
        previous = [item for item in emitted if item["bar_index"] < count - 1]
        if previous != history:
            raise BacktestError("EXTERNAL_NONCAUSAL_PREFIX", "script changed earlier decisions when history grew")
        current = [item for item in emitted if item["bar_index"] == count - 1]
        if len(current) > 64 or len(previous) + len(current) != len(emitted):
            raise BacktestError("EXTERNAL_UNSUPPORTED", "at most 64 order intents per bar")
        history.extend(current)
        orders.configure(latest.get("pyramiding", 1))
        check_risk_response(orders, wire, latest)
        return orders.translate(current, event.sequence)

    events = [MarketEvent(sequence=index + 1, event_time_ms=interval.next_ms(bar["time"] * 1000) - 1, role="BARS",
                          payload={"open_time_ms": bar["time"] * 1000, "close_time_ms": interval.next_ms(bar["time"] * 1000) - 1,
                                   **{key: str(bar[key]) for key in ("open", "high", "low", "close", "volume")}})
              for index, bar in enumerate(wire["bars"])]
    execution_passes = None
    if wire.get("pine_print_tick_contract"):
        from .pine_print_tick_execution import run_clock
        execution=run_clock(_pine_stream,kernel,orders,wire,state=clock,target=target,
            discovery_only=_discovery_only,capture_checkpoint=capture,_capture_owned=_capture_owned,
            _consume_state=_consume_resume)
        if _discovery_only:
            return None
        latest,history,accounts,execution_passes,clock,last_request=execution
    elif wire.get("pine_history_tick_contract"):
        from .pine_history_tick_execution import run_clock
        execution=run_clock(_pine_stream,kernel,orders,wire,state=clock,target=target,
            discovery_only=_discovery_only,capture_checkpoint=capture,_capture_owned=_capture_owned,
            _consume_state=_consume_resume)
        if _discovery_only:
            return None
        latest,history,accounts,execution_passes,clock,last_request=execution
    elif wire.get("pine_bar_path_contract"):
        from .pine_bar_clock import run_bar_clock
        latest,history,accounts,execution_passes,clock=run_bar_clock(kernel,orders,wire,plugin,evaluate,cancelled,deadline,state=clock,target=target)
    elif wire.get("fill_recalculation"):
        from .external_feedback import run_feedback_clock
        latest,history,accounts,execution_passes,clock=run_feedback_clock(kernel,orders,wire,plugin,evaluate,cancelled,deadline,state=clock,target=target)
    elif fidelity == "BAR_APPROX":
        from app.simulation.closing_tick import match_closing_tick
        kernel.run(events[cursor:target], strategy, finalize=target==len(wire["bars"]),
            **({"close_callback": lambda bar, seq: match_closing_tick(kernel, bar, seq)} if wire.get("closing_ticks") else {}))
    else:
        from .external_market import run_print_clock
        clock=run_print_clock(kernel,wire,strategy,cancelled,state=clock,target=target)
    if request_feed is not None:
        clock["request_feed"] = request_feed.snapshot()
    report = json.loads(json.dumps(asdict(kernel.result()), default=str))
    from .pine_order_metadata import report_fields, enrich_orders
    result={"execution_mode": "CANDLESCOPE", "account_authority": "candlescope", "identity": wire["identity"],
            "account_model": kernel.account_model,
            "evaluation_contract": latest.get("evaluation_contract", "historical-prefix/1"),
            "host_runtime_identity": wire["host_runtime_identity"],
            "fill_model": kernel.fill_policy, "fidelity": ("AGG_TRADE_TAPE" if fidelity == "TRADE_TAPE" and kernel.source_kind == "AGG_TRADE" else fidelity),
            "trades": [{**fill, "time": fill["event_time_ms"] / 1000,
                        "script_order_id": orders.bindings[fill["order_id"]][0],
                        "closed_entries": allocation["closed"], "opened_entry": allocation["opened"],
                        **report_fields(allocation.get("annotation", {}))}
                       for fill, allocation in zip(report["fills"], orders.allocations, strict=True)],
            "closed_trades": closed_trades(report["fills"]),
            "orders": enrich_orders([{**order,"script_order_id":orders.bindings[order["order_id"]][0]} for order in report["orders"]],
                orders.report().get("order_annotations", {})),
            "position": report["ledger"]["account"],
            "equity": [{"time": row["event_time_ms"] / 1000, "value": float(row["equity"])} for row in report["equity_curve"]],
            "graphics": latest.get("graphics", []), "diagnostics": report["rejected"],
            "raw_output": {"depth_model": ({"queue_exact": False, "queue_policy": "displayed_size_plus_earlier_own_orders",
                            "cancellations_advance_queue": False, "taker_clock": "next_trade_print",
                            "taker_capacity": "remaining_visible_depth", "passive_capacity": "same_price_opposite_aggressor_print"}
                            if fidelity == "BOOK_DEPTH" else kernel.disclosure() if fidelity == "BOOK_SAMPLED" else None),
                           "execution_provenance": wire.get("execution_provenance", {}),
                           "entry_allocation": orders.report(), "kernel": report, "account_feedback": accounts, "intent_history": history,
                           "execution_passes": execution_passes, "strategy_output": latest.get("raw_output", {})}}
    if risk_stops is not None and risk_stops.state is not None:
        result["pine_risk_stops"] = risk_stops.report()
    quantity = (wire.get("pine_host_control") or {}).get("default_quantity")
    if quantity is not None:
        result["raw_output"]["default_quantity"] = dict(quantity)
    if wire.get("pine_bar_path_contract"):
        result["raw_output"]["pine_bar_path"] = {"contract": wire["pine_bar_path_contract"],
            "vertices": "NEAREST_EXTREME_FIRST_LOW_ON_TIE", "timestamps": "LINEAR_INTERPOLATION_SYNTHETIC",
            "physical_tape": False, "official_oracle_verified": False}
        result["raw_output"]["execution_schedule"] = clock["groups"]
        if wire.get("pine_v2_bar_contract"):
            result["raw_output"]["pine_bar_path"].update(v2_contract=wire["pine_v2_bar_contract"],
                capacity_policy="SHARED_BAR_VOLUME_PARTICIPATION" if kernel.execution_model_revision else "UNCAPPED",
                mark_authority="HISTORICAL_MARK_INDEX" if kernel.account_model == "LINEAR_PERP_ONE_WAY_V2" else "PATH_MARK")
            result["raw_output"]["account_provenance"] = wire.get("account_provenance", {})
    if wire.get("pine_v2_print_contract"):
        result["raw_output"]["pine_v2_print_account"] = {
            "contract": wire["pine_v2_print_contract"], "mark_authority": "HISTORICAL_MARK_INDEX",
            "account_event_order": "ACCOUNT_BEFORE_MARKET_ON_TIES",
            "pre_print_account_fill_callback": "NEXT_OBSERVED_PRINT",
            "physical_capacity_policy": kernel.fill_policy, "official_oracle_verified": False}
        result["raw_output"]["account_provenance"] = wire.get("account_provenance", {})
    if wire.get("pine_print_tick_contract"):
        result["raw_output"].update(pine_print_tick_contract=wire["pine_print_tick_contract"],execution_schedule=clock["groups"])
    if wire.get("closing_ticks"):
        result["raw_output"]["closing_tick_contract"] = "candlescope.pine-closing-tick/1"
        result["raw_output"]["closing_execution"] = {
            "price_policy": "VISIBLE_BOOK_QUOTES" if fidelity.startswith("BOOK") else "REVEALED_BAR_CLOSE",
            "capacity_policy": ("SHARED_BAR_VOLUME_PARTICIPATION" if wire.get("pine_v2_bar_contract") and kernel.execution_model_revision else "REMAINING_VISIBLE_DEPTH" if fidelity in {"BOOK_DEPTH", "BOOK_SAMPLED"}
                else "REMAINING_BAR_VOLUME_PROXY" if fidelity == "BOOK_ASSISTED" else "HOST_BAR_OR_TAPE_APPROXIMATION"),
            "passive_prints_inferred": False, "actual_close_auction_verified": False}
        if result["raw_output"]["depth_model"] is not None:
            result["raw_output"]["depth_model"]["taker_clock"] = "next_trade_print_or_explicit_script_close"
    if wire.get("pine_cost_contract") and not _cost_scenario and target == len(wire["bars"]):
        from .workbench_sensitivity import build_matrix, skipped_matrix
        result["cost_sensitivity"] = (skipped_matrix() if wire.get("cost_sensitivity_mode") == "SKIP"
            else build_matrix(plugin, wire, scenario_runner, cancelled, result, deadline=deadline))
    if capture:
        from .external_replay import make_state
        return result,make_state(wire,target,kernel,orders,accounts,history,latest,clock,last_request,
            risk_stops=risk_stops,_owned_output=_capture_owned)
    return result
