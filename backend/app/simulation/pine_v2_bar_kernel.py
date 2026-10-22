"""Historical OHLC matching with causal V2 account events and shared capacity."""
from copy import deepcopy
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation

from app.market_dataset.snapshot import MarketDatasetError, MarketEvent, sha256_hex
from .account_execution import publish_account_liquidation
from .closing_tick import crosses_limit, triggers_stop
from .execution_realism import EXECUTION_REALISM_V2, PINE_BAR_PATH_SCENARIO, PINE_BAR_FILL_POLICY
from .kernel import SimulationKernel
from .linear_perp_account_v2 import LinearPerpetualAccountV2
from .pine_bar_kernel import PineBarKernel, LIVE
from .pine_chart_kernel import PineChartBarKernel

CONTRACT = "candlescope.pine-v2-bar/1"
AUXILIARY = {"INSTRUMENT_RULES", "MARK_INDEX", "FUNDING"}


@dataclass(slots=True)
class PineV2BarKernel(PineChartBarKernel):
    v2_path_contract = CONTRACT
    fill_policy: str = PINE_BAR_FILL_POLICY
    _capacity_left: Decimal | None = None
    _auxiliary: list = field(default_factory=list, repr=False)
    _auxiliary_cursor: int = 0
    _active_bar: MarketEvent | None = field(default=None, repr=False)
    _observation_point: MarketEvent | None = field(default=None, repr=False)
    _pending_callbacks: list = field(default_factory=list, repr=False)
    _delivered_account_callbacks: list = field(default_factory=list, repr=False)
    _last_bar_close_ms: int | None = None
    _last_path_price: Decimal | None = None
    _callback: object = field(default=None, repr=False)
    _failed_bar: bool = field(default=False, repr=False)

    def __post_init__(self):
        SimulationKernel.__post_init__(self)
        if self.execution_model_revision not in {None, EXECUTION_REALISM_V2}:
            raise MarketDatasetError("unknown Pine path execution model", code="FIDELITY_UNSUPPORTED")

    def _supports_bar_path_scenario(self):
        return self.bar_path_scenario == PINE_BAR_PATH_SCENARIO

    def _account_curve_sequence(self, event):
        return event.sequence

    def _mark(self, price):
        if not isinstance(self.account, LinearPerpetualAccountV2):
            self.account.mark = price

    def _point(self, price, timestamp, *, vertex, phase="PATH"):
        prototype = MarketEvent(0, timestamp, "BARS", {
            **{key: str(price) for key in ("open", "high", "low", "close", "price")},
            "execution_phase": phase, "path_vertex": vertex, "path_contract": CONTRACT,
            "path_source": self._wire(self._active_bar)})
        self._observation_point = None
        # Account events at the same synthetic timestamp precede matching.
        while self._auxiliary_cursor < len(self._auxiliary) and self._auxiliary[self._auxiliary_cursor].event_time_ms <= timestamp:
            source = self._auxiliary[self._auxiliary_cursor]
            self._apply_auxiliary(source, prototype if source.event_time_ms == timestamp else None)
            self._auxiliary_cursor += 1
        self.path_sequence += 1
        point = replace(prototype, sequence=self.path_sequence)
        self._observation_point = point
        self._last_path_price = price
        self._last_event = point
        self._mark(price)
        self._market_event_count += 1
        self._apply_funding(point)
        if self.market_observer is not None:
            self.market_observer(point)
        pending, self._pending_callbacks = self._pending_callbacks, []
        for _receipt in pending:
            self._delivered_account_callbacks.append(_receipt["order_id"])
            self._callback(self._active_bar, point, "order_fill")
        self._match_point(point, vertex=vertex)
        self._mark(price)
        self._record_equity(point)
        return point

    def _apply_auxiliary(self, source, point=None):
        if source.role not in AUXILIARY:
            raise MarketDatasetError("unsupported Pine account event", code="FIDELITY_MISLABEL")
        self.path_sequence += 1
        price = (self._last_path_price or Decimal(1)) if point is None else Decimal(point.payload["price"])
        self._last_event = MarketEvent(self.path_sequence, source.event_time_ms, source.role,
            {**source.payload, "price": str(price), "close": str(price), "path_source": self._wire(source),
             "execution_phase": "PATH_AUX", "path_contract": CONTRACT})
        if source.role == "FUNDING" and self.market_observer is not None:
            self.market_observer(self._last_event)
        self.account.apply(source)
        publish_account_liquidation(self)
        if self.market_observer is not None:
            self.market_observer(self._last_event)
        if self.chart_bar_count > 0:
            self._record_equity_point({"sequence": self.path_sequence, "event_time_ms": source.event_time_ms,
                "equity": str(self.account.equity()), "position_qty": str(self.account.position_qty),
                **({"wallet_balance": str(self.account.quote_balance), "available_balance": str(self.account.available_balance())}
                   if isinstance(self.account, LinearPerpetualAccountV2) else {})})

    def _interleave_point(self, start, finish, begin_ms, end_ms, price, timestamp, endpoint):
        if self._auxiliary_cursor < len(self._auxiliary):
            stamp = self._auxiliary[self._auxiliary_cursor].event_time_ms
            if stamp < timestamp:
                value = start if end_ms == begin_ms else start + (finish - start) * Decimal(stamp - begin_ms) / (end_ms - begin_ms)
                return value, stamp, False
        return price, timestamp, endpoint

    def _match_point(self, event, *, vertex, order_ids=None):
        from .v2_margin import reprice
        reprice(self, event)
        price = Decimal(event.payload["price"])
        eligible = []
        for _ in range(10000):
            progress = False
            for order in tuple(self._live_orders()):
                if order_ids is not None and order.order_id not in order_ids:
                    continue
                if order.eligible_after_sequence > event.sequence or not self._prepare(order, event):
                    continue
                if order.order_id not in eligible:
                    eligible.append(order.order_id)
                if order.type == "STOP_LIMIT" and not order.activated and triggers_stop(order, price):
                    order.activated = True
                limit = order.type == "LIMIT" or (order.type == "STOP_LIMIT" and order.activated)
                if not ((limit and crosses_limit(order, price)) or (order.type == "STOP" and triggers_stop(order, price))
                        or (order.type == "MARKET" and vertex)):
                    continue
                capacity = self._capacity_left
                step = getattr(self.account, "step", None) or self.qty_step
                if capacity is not None and step is not None:
                    capacity = (capacity // step) * step
                if capacity is not None and capacity <= 0:
                    continue
                if isinstance(self.account, LinearPerpetualAccountV2):
                    self.account.validate_ready()
                fill_price = price if limit else price + price * self.slippage_bps / 10000 * (1 if order.side == "BUY" else -1)
                reason = ("PINE_BAR_CLOSE" if event.payload["execution_phase"] == "PINE_BAR_CLOSE" else
                          "LIMIT_TOUCH" if limit else "STOP_TOUCH" if order.type == "STOP" else
                          "MARKET_OBSERVATION_VERTEX" if order_ids is not None else "MARKET_NEXT_VERTEX")
                used = self._fill(order, event.sequence, fill_price, reason, capacity)
                if self._capacity_left is not None:
                    self._capacity_left -= used
                self._mark(price)
                progress = used > 0
                if progress:
                    break
            if not progress:
                break
        else:
            raise MarketDatasetError("Pine V2 path matching budget exceeded", code="BUDGET_EXCEEDED")
        if self.execution_model_revision == EXECUTION_REALISM_V2:
            for order in tuple(self._live_orders()):
                if order.order_id in eligible and self._order_tif.get(order.order_id) == "IOC" and order.status in LIVE:
                    order.status = "EXPIRED"
                    self._lifecycle(order, "EXPIRED", reason="IOC_REMAINDER")
                    if isinstance(self.account, LinearPerpetualAccountV2):
                        self.account.release_order_margin(order.order_id, event_time_ms=event.event_time_ms)

    @staticmethod
    def _wire(event):
        return None if event is None else {"sequence": event.sequence, "event_time_ms": event.event_time_ms,
            "role": event.role, "payload": dict(event.payload)}

    def snapshot(self, *, history_encoder=None):
        if self._active_bar is not None or self._failed_bar:
            raise MarketDatasetError("commit the complete Pine V2 bar before snapshot", code="CHECKPOINT_CORRUPT")
        return {**super(PineV2BarKernel, self).snapshot(history_encoder=history_encoder), "pine_v2_bar": {
            "contract": CONTRACT, "last_bar_close_ms": self._last_bar_close_ms,
            "pending_callbacks": deepcopy(self._pending_callbacks),
            "delivered_account_callbacks": list(self._delivered_account_callbacks),
            "last_path_price": None if self._last_path_price is None else str(self._last_path_price),
            "capacity_left": None if self._capacity_left is None else str(self._capacity_left)}}

    def restore(self, payload):
        state, chart = payload.get("pine_v2_bar") or {}, payload.get("pine_chart_bar") or {}
        if (state.get("contract") != CONTRACT or chart.get("contract") != "candlescope.pine-chart-bar/1"
                or type(chart.get("sequence")) is not int or type(chart.get("bar_count")) is not int
                or not 0 <= chart["bar_count"] <= chart["sequence"]
                or (chart["sequence"] == 0 and chart.get("time_ms") is not None)
                or (chart["sequence"] > 0 and type(chart.get("time_ms")) is not int)
                or (chart["bar_count"] > 0 and type(state.get("last_bar_close_ms")) is not int)
                or (chart["bar_count"] == 0 and state.get("last_bar_close_ms") is not None)
                or not isinstance(state.get("pending_callbacks"), list)
                or not isinstance(state.get("delivered_account_callbacks"), list)
                or any(not isinstance(value, str) for value in state["delivered_account_callbacks"])
                or any(not isinstance(row, dict) or set(row) != {"order_id", "execution_time_ms"}
                       or not isinstance(row["order_id"], str) or type(row["execution_time_ms"]) is not int
                       for row in state["pending_callbacks"])):
            raise MarketDatasetError("Pine V2 path checkpoint differs", code="CHECKPOINT_CORRUPT")
        PineBarKernel.restore(self, payload)
        self.source_sequence, self.source_time_ms, self.chart_bar_count = chart["sequence"], chart.get("time_ms"), chart["bar_count"]
        self._last_bar_close_ms = state.get("last_bar_close_ms")
        self._pending_callbacks = deepcopy(state["pending_callbacks"])
        self._delivered_account_callbacks = list(state.get("delivered_account_callbacks") or [])
        try:
            self._capacity_left = None if state.get("capacity_left") is None else Decimal(state["capacity_left"])
            self._last_path_price = None if state.get("last_path_price") is None else Decimal(state["last_path_price"])
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise MarketDatasetError("invalid Pine capacity checkpoint", code="CHECKPOINT_CORRUPT") from exc
        if ((self._capacity_left is not None and (not self._capacity_left.is_finite() or self._capacity_left < 0))
                or (self._last_event is not None and self._last_event.event_time_ms != self.source_time_ms)
                or (self._last_bar_close_ms is not None and self._last_bar_close_ms > self.source_time_ms)
                or self.path_sequence < self.chart_bar_count * 4):
            raise MarketDatasetError("Pine V2 path cursors differ", code="CHECKPOINT_CORRUPT")
        if ((self.chart_bar_count > 0 and self._last_path_price is None)
                or self._last_path_price is not None and (not self._last_path_price.is_finite() or self._last_path_price <= 0)):
            raise MarketDatasetError("Pine path quote checkpoint differs", code="CHECKPOINT_CORRUPT")
        pending_ids = [row.get("order_id") for row in self._pending_callbacks]
        ids = pending_ids + self._delivered_account_callbacks
        if len(set(ids)) != len(ids) or set(ids) != set(self._account_execution_receipts):
            raise MarketDatasetError("Pine account callback receipts differ", code="CHECKPOINT_CORRUPT")
        fills = {row.order_id: row for row in self.fills}
        if any(row.get("execution_time_ms") != fills[row["order_id"]].event_time_ms for row in self._pending_callbacks):
            raise MarketDatasetError("Pine pending account callback time differs", code="CHECKPOINT_CORRUPT")
        self._failed_bar = False

    def _financial_result(self):
        fills, ledger = super(PineV2BarKernel, self)._financial_result()
        if self.execution_model_revision == EXECUTION_REALISM_V2:
            for fill, point in zip(fills, self._fill_source_events, strict=True):
                source = point.payload.get("path_source")
                if source is not None:
                    kind = source["role"] if source["role"] != "BARS" else "SYNTHETIC_BAR_PATH"
                    fill.update(source_sequence=source["sequence"], source_event_time_ms=source["event_time_ms"],
                        source_event_hash="sha256:" + sha256_hex(source), path_sequence=point.sequence,
                        path_time_ms=point.event_time_ms, synthetic_path=source["role"] == "BARS")
                    if fill["reason"] == "ACCOUNT_LIQUIDATION":
                        fill["triggering_event_kind"] = kind
                    else:
                        fill["source_event_kind"] = "SCRIPT_BAR_CLOSE" if point.payload.get("execution_phase") == "PINE_BAR_CLOSE" else kind
        ledger["pine_v2_path"] = {"contract": CONTRACT, "capacity_left": None if self._capacity_left is None else str(self._capacity_left),
            "pending_account_callbacks": deepcopy(self._pending_callbacks),
            "delivered_account_callbacks": list(self._delivered_account_callbacks)}
        return fills, ledger

    def result(self):
        result = SimulationKernel.result(self)
        return replace(result, report_hash="sha256:" + sha256_hex({"parent": result.report_hash, "path_contract": CONTRACT}))

    def run(self, events, strategy, *, warmup_events=0, finalize=False, checkpoint_callback=None, fill_callback=None,
            vertex_callback=None, **options):
        if fill_callback is None or warmup_events or options or self._failed_bar:
            raise MarketDatasetError("Pine V2 requires its historical callback clock", code="FIDELITY_UNSUPPORTED")
        prior = self.execution_reporter
        checked_sequence, checked_time = self.source_sequence, self.source_time_ms
        pending = []

        def apply(plan, point):
            self._record_decision(plan, point)
            self._enqueue_many(plan, current_sequence=point.sequence)

        def callback(bar, point, trigger):
            if vertex_callback is None:
                apply(fill_callback(bar, point, trigger), point)

        def report(value):
            if prior is not None:
                prior(value)
            if value.get("fill"):
                point = self._observation_point
                if point is None:
                    self._pending_callbacks.append({"order_id": value["order_id"], "execution_time_ms": value["fill"]["event_time_ms"]})
                else:
                    if value.get("account_liquidation"):
                        self._delivered_account_callbacks.append(value["order_id"])
                    callback(self._active_bar, point, "closing_fill" if point.payload["execution_phase"] == "PINE_BAR_CLOSE" else "order_fill")

        def close(point):
            plan=strategy((self._active_bar,), self._active_bar)
            if vertex_callback is None or plan: apply(plan,point)
            if self.process_orders_on_close:
                self.closing_tick()

        self.execution_reporter, self._callback = report, callback
        try:
            for source in events:
                if self.paused:
                    break
                if (type(source.sequence) is not int or source.sequence <= checked_sequence
                        or checked_time is not None and source.event_time_ms < checked_time):
                    raise MarketDatasetError("Pine V2 source cursor moved backwards", code="DATA_GAP_REJECTED")
                if checked_sequence and source.sequence != checked_sequence + 1:
                    if self.gap_policy == "PAUSE":
                        self.paused = True
                        break
                    if self.gap_policy != "SKIP_WITH_WARNING":
                        raise MarketDatasetError("Pine V2 source sequence gap", code="DATA_GAP_REJECTED")
                    self.ambiguity_count += 1
                checked_sequence, checked_time = source.sequence, source.event_time_ms
                if source.role in AUXILIARY:
                    if self._last_bar_close_ms is not None and source.event_time_ms <= self._last_bar_close_ms:
                        raise MarketDatasetError("account event would revise a committed Pine bar", code="DATA_QUALITY_FAILED")
                    pending.append(source)
                    if len(pending) > 100000:
                        raise MarketDatasetError("too many account events in a Pine bar", code="BUDGET_EXCEEDED")
                    continue
                if source.role != "BARS":
                    raise MarketDatasetError("unknown Pine V2 source role", code="FIDELITY_MISLABEL")
                if (source.event_time_ms != int(source.payload["close_time_ms"])
                        or self.source_time_ms is not None and int(source.payload["open_time_ms"]) <= self.source_time_ms):
                    raise MarketDatasetError("Pine V2 bar boundary differs", code="DATA_QUALITY_FAILED")
                self._active_bar, self._auxiliary, self._auxiliary_cursor = source, pending, 0
                volume = Decimal(str(source.payload.get("volume", 0)))
                if not volume.is_finite() or volume < 0:
                    raise MarketDatasetError("invalid Pine V2 bar volume", code="DATA_QUALITY_FAILED")
                self._capacity_left = volume * self.participation_rate if self.execution_model_revision == EXECUTION_REALISM_V2 else None
                self.walk_bar(source, close, on_vertex=(
                    (lambda point, index: vertex_callback(source, point, index)) if vertex_callback is not None else None))
                if self._auxiliary_cursor != len(self._auxiliary):
                    raise MarketDatasetError("Pine account event beyond its bar", code="DATA_QUALITY_FAILED")
                self.source_sequence, self.source_time_ms = source.sequence, source.event_time_ms
                self._last_bar_close_ms = source.event_time_ms
                self.chart_bar_count += 1
                self._record_equity_point({"sequence": self.path_sequence, "event_time_ms": source.event_time_ms,
                    "equity": str(self.account.equity()), "position_qty": str(self.account.position_qty),
                    **({"wallet_balance": str(self.account.quote_balance), "available_balance": str(self.account.available_balance())}
                       if isinstance(self.account, LinearPerpetualAccountV2) else {})})
                self._active_bar, self._observation_point, pending, self._auxiliary = None, None, [], []
                if checkpoint_callback is not None:
                    checkpoint_callback(source)
            for source in pending:
                self._apply_auxiliary(source)
                self.source_sequence, self.source_time_ms = source.sequence, source.event_time_ms
                if checkpoint_callback is not None:
                    checkpoint_callback(source)
            self._append_terminal_curve_point()
            if finalize:
                self.finalize_orders()
        except BaseException:
            self._failed_bar = True
            raise
        finally:
            self.execution_reporter, self._callback, self._active_bar, self._observation_point = prior, None, None, None
            self._auxiliary, self._auxiliary_cursor = [], 0
        return self.result()
