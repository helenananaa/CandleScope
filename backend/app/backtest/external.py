"""CandleScope-owned BAR matching with actual Pine/Pyne account feedback.

V2 supports price orders, brackets and separate bar/print execution clocks.
No native fills are accepted. The kernel remains the only accounting authority.
"""
from __future__ import annotations

from dataclasses import asdict
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


def host_identity():
    import app.simulation.kernel as kernel_module
    files = [Path(__file__), Path(__file__).with_name("native_session.py"), Path(__file__).with_name("external_orders.py"), Path(__file__).with_name("external_market.py"), Path(__file__).with_name("external_feedback.py"), *sorted(Path(kernel_module.__file__).parent.rglob("*.py"))]
    checksum = hashlib.sha256()
    for path in files:
        checksum.update(path.name.encode())
        checksum.update(path.read_bytes())
    return {"contract": "external-broker/1", "host_model": "SAMPLED_BOOK_VISIBLE_TAKER_V9", "code_sha256": checksum.hexdigest()}


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


def run_external_host(plugin, wire, runner, cancelled):
    from .native import invoke
    from .native_session import SessionWorker
    if runner is invoke and wire["identity"].get("adapter") in {"pine-external/5", "pyne-external/4"}:
        worker = SessionWorker(plugin, wire, cancelled, evaluator=True)
        try:
            return _run_external_host(plugin, wire,
                lambda _plugin, payload, **kwargs: worker.request(payload, **kwargs), cancelled)
        finally:
            worker.close()
    return _run_external_host(plugin, wire, runner, cancelled)


def _run_external_host(plugin, wire, runner, cancelled):
    if wire.get("host_runtime_identity") != host_identity():
        raise BacktestError("NATIVE_IDENTITY_MISMATCH", "host matching code changed after submission")
    settings = wire["host_settings"]
    fidelity = wire.get("execution_fidelity", "BAR_APPROX")
    from app.simulation.trade_kernel import TradeSimulationKernel
    from app.simulation.book_kernel import BookAssistedKernel
    from app.simulation.depth_kernel import DepthQueueKernel
    from app.simulation.sampled_book_kernel import SampledBookKernel
    kernel_type = {"BAR_APPROX":SimulationKernel,"BOOK_ASSISTED":BookAssistedKernel,
                   "TRADE_TAPE":TradeSimulationKernel,"BOOK_DEPTH":DepthQueueKernel,"BOOK_SAMPLED":SampledBookKernel}[fidelity]
    kernel = kernel_type(initial_balance=Decimal(str(settings["initial_balance"])),
                              slippage_bps=Decimal(str(settings["slippage_bps"])),
                              taker_fee_bps=Decimal(str(settings["taker_fee_bps"])))
    interval = parse_interval_spec(wire["interval"])
    accounts, history, latest = [], [], {}
    orders = ExternalOrders(kernel, price_tick=settings.get("price_tick"), fidelity=fidelity)
    deadline = time.monotonic() + 120

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
                         "netprofit": float(account.quote_balance - kernel.initial_balance), "openprofit": float(account.unrealized())})
        request = {**{key: value for key, value in wire.items() if key != "execution_events"}, "bars": wire["bars"][:count], "accounts": accounts}
        request["contexts"] = visible_contexts(wire, interval.next_ms(wire["bars"][count - 1]["time"] * 1000))
        latest = runner(plugin, request, cancelled=cancelled, timeout=max(0.1, deadline - time.monotonic()))
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
        return orders.translate(current, event.sequence)

    events = [MarketEvent(sequence=index + 1, event_time_ms=interval.next_ms(bar["time"] * 1000) - 1, role="BARS",
                          payload={"open_time_ms": bar["time"] * 1000, "close_time_ms": interval.next_ms(bar["time"] * 1000) - 1,
                                   **{key: str(bar[key]) for key in ("open", "high", "low", "close", "volume")}})
              for index, bar in enumerate(wire["bars"])]
    execution_passes = None
    if wire.get("fill_recalculation"):
        from .external_feedback import run_feedback_clock
        latest, history, accounts, execution_passes = run_feedback_clock(kernel, orders, wire, plugin, runner, cancelled, deadline)
    elif fidelity == "BAR_APPROX":
        kernel.run(events, strategy, finalize=True)
    else:
        from .external_market import run_print_clock
        run_print_clock(kernel, wire, strategy, cancelled)
    report = json.loads(json.dumps(asdict(kernel.result()), default=str))
    return {"execution_mode": "CANDLESCOPE", "account_authority": "candlescope", "identity": wire["identity"],
            "host_runtime_identity": wire["host_runtime_identity"],
            "fill_model": kernel.fill_policy, "fidelity": ("AGG_TRADE_TAPE" if fidelity == "TRADE_TAPE" and kernel.source_kind == "AGG_TRADE" else fidelity),
            "trades": [{**fill, "time": fill["event_time_ms"] / 1000,
                        "script_order_id": orders.bindings[fill["order_id"]][0],
                        "closed_entries": allocation["closed"], "opened_entry": allocation["opened"]}
                       for fill, allocation in zip(report["fills"], orders.allocations, strict=True)],
            "orders": [{**order,"script_order_id":orders.bindings[order["order_id"]][0]} for order in report["orders"]],
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
