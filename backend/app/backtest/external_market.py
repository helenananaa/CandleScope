"""Frozen execution data and separate bar-decision / print-matching clocks."""
from decimal import Decimal
import math
from app.market_dataset.snapshot import MarketEvent
from app.market_dataset.trades import assert_trade_stream
from app.simulation.book_kernel import assert_book_chain
from app.data_engine.interval_policy import parse_interval_spec
from .errors import BacktestError


def freeze_execution(native, payload, bars):
    mode = payload.get("execution_fidelity", "BAR_APPROX")
    data = payload.get("execution_data")
    if mode == "BAR_APPROX":
        if payload.get("fill_recalculation"):
            raise BacktestError("EXTERNAL_UNSUPPORTED", "fill callbacks require a frozen trade tape")
        if data: raise BacktestError("FIDELITY_MISLABEL", "BAR mode cannot accept print data")
        return []
    if data is None:
        if mode in {"BOOK_ASSISTED", "BOOK_DEPTH", "BOOK_SAMPLED"}:
            raise BacktestError("DATA_ROLE_MISSING", "upload a frozen trade and book dataset")
        from .runtime import _read_trade_events
        runtime = native.runtime
        dataset = runtime._freeze_trade_dataset(exchange=payload.get("exchange", "binance"), market_type=payload.get("market_type", "usdm"),
            symbol=payload["context"]["symbol"].split(":")[-1], start_time_ms=payload["start_time_ms"], end_time_ms=payload["end_time_ms"])
        events = _read_trade_events(runtime._require_trade_archive(), dataset, max_events=runtime.settings.max_trade_events)
    else:
        if data["symbol"] != payload["context"]["symbol"].split(":")[-1]:
            raise BacktestError("DATA_SNAPSHOT_MISMATCH", "execution symbol differs from chart")
        events = tuple(MarketEvent(sequence=i+1, event_time_ms=item["time_ms"], role=item["role"], payload=item["payload"]) for i,item in enumerate(data["events"]))
    validate_execution(events, bars, payload["interval"], mode)
    return [{"sequence": e.sequence, "event_time_ms": e.event_time_ms, "role": e.role, "payload": dict(e.payload)} for e in events]


def validate_execution(events, bars, interval, mode):
    trades = tuple(e for e in events if e.role == "TRADES")
    assert_trade_stream(trades)
    step = parse_interval_spec(interval)
    begin, end = bars[0]["time"] * 1000, step.next_ms(bars[-1]["time"] * 1000)
    previous_time = begin
    previous_id = None
    book_seen = False
    depth = None
    if mode == "BOOK_DEPTH":
        from app.simulation.depth_kernel import DepthQueueKernel
        depth = DepthQueueKernel()
    elif mode == "BOOK_SAMPLED":
        from app.simulation.sampled_book_kernel import SampledBookKernel
        depth = SampledBookKernel()
    for event in events:
        if not begin <= event.event_time_ms < end or event.event_time_ms < previous_time:
            raise BacktestError("DATA_QUALITY_FAILED", "execution timestamps outside ordered frozen range")
        previous_time = event.event_time_ms
        names = ("price", "qty") if event.role == "TRADES" else () if depth else ("bid", "ask")
        for name in names:
            value = float(event.payload.get(name, "nan"))
            if not math.isfinite(value) or value <= 0:
                raise BacktestError("DATA_QUALITY_FAILED", "execution prices and quantities must be positive")
        if event.role == "ORDER_BOOK":
            if depth:
                depth._apply_book(event)
            elif mode != "BOOK_ASSISTED" or float(event.payload["bid"]) > float(event.payload["ask"]):
                raise BacktestError("FIDELITY_MISLABEL", "invalid book for execution mode")
            if not book_seen and event.payload.get("snapshot") is not True:
                raise BacktestError("DATA_QUALITY_FAILED", "book must begin with a snapshot")
            book_seen = True
        elif event.role == "TRADES":
            if mode in {"BOOK_ASSISTED", "BOOK_DEPTH", "BOOK_SAMPLED"} and not book_seen:
                raise BacktestError("DATA_QUALITY_FAILED", "trade precedes book snapshot")
            if depth and event.payload.get("aggressor_side") not in {"BUY", "SELL"}:
                raise BacktestError("DATA_QUALITY_FAILED", "depth mode requires trade aggressor_side")
            if mode == "BOOK_SAMPLED" and depth.sample_time_ms == event.event_time_ms:
                raise BacktestError("DATA_QUALITY_FAILED", "same-ms trades must precede the new book sample")
            source_id = int(event.payload.get("source_sequence") or event.sequence)
            if previous_id is not None and source_id != previous_id + 1:
                raise BacktestError("DATA_GAP_REJECTED", "trade IDs are not contiguous")
            previous_id = source_id
        else:
            raise BacktestError("FIDELITY_MISLABEL", "unsupported execution role")
    if mode == "BOOK_ASSISTED": assert_book_chain(tuple(events))
    # Chart history must be derived from this exact print tape, never unrelated OHLCV.
    cursor = 0
    for bar in bars:
        selected = []
        boundary = step.next_ms(bar["time"] * 1000)
        while cursor < len(trades) and trades[cursor].event_time_ms < boundary:
            selected.append(trades[cursor]); cursor += 1
        if not selected: raise BacktestError("DATA_GAP_REJECTED", "no prints for a chart bar")
        prices = [Decimal(str(e.payload["price"])) for e in selected]
        computed = dict(open=prices[0], high=max(prices), low=min(prices), close=prices[-1], volume=sum((Decimal(str(e.payload["qty"])) for e in selected), Decimal(0)))
        if any(not math.isclose(float(computed[k]), bar[k], rel_tol=1e-10, abs_tol=1e-10) for k in computed):
            raise BacktestError("DATA_SNAPSHOT_MISMATCH", "chart OHLCV differs from execution tape")


def run_print_clock(kernel, wire, strategy, cancelled):
    interval = parse_interval_spec(wire["interval"])
    events = [MarketEvent(**item) for item in wire["execution_events"]]
    kernel.source_kind = assert_trade_stream(tuple(e for e in events if e.role == "TRADES"))
    bar_cursor, last_sequence = 0, 0
    def decide():
        nonlocal bar_cursor
        bar = wire["bars"][bar_cursor]
        time_ms = interval.next_ms(bar["time"] * 1000) - 1
        kernel.account.mark = Decimal(str(bar["close"]))
        decision_event = MarketEvent(last_sequence, time_ms, "TRADES", {"price": str(bar["close"]), "qty": "0"})
        kernel._last_event = decision_event
        intents = strategy((), decision_event)
        kernel.decisions.append({"sequence": last_sequence, "watermark_ms": time_ms, "intents": intents, "signal_bar": bar_cursor})
        kernel._enqueue_many(intents, current_sequence=last_sequence)
        bar_cursor += 1
    for event in events:
        if cancelled.is_set(): raise BacktestError("NATIVE_CANCELLED", "execution cancelled")
        while bar_cursor < len(wire["bars"]) and interval.next_ms(wire["bars"][bar_cursor]["time"] * 1000) <= event.event_time_ms:
            decide()
        kernel._last_event = event
        if event.role == "ORDER_BOOK":
            kernel._apply_book(event)
        else:
            kernel.account.mark = Decimal(str(event.payload["price"]))
            kernel._match(event)
            kernel.equity_curve.append({"sequence": event.sequence, "event_time_ms": event.event_time_ms,
                "equity": str(kernel.account.equity()), "position_qty": str(kernel.account.position_qty)})
        last_sequence = event.sequence
    while bar_cursor < len(wire["bars"]): decide()
    kernel.finalize_orders()
