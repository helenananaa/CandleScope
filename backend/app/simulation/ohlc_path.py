"""Pine OHLC path clocks of the Host bar kernel (ADR-BACKTEST-015 P6b).

The Host bar kernel (``SimulationKernel``) matches bars on one of four declared clocks:

- ``BAR``: one worst-case decision per bar (``OHLC_WORST_CASE_STOP_FIRST_V1``);
- ``PINE_PATH``: a deterministic OHLC path with continuous price-order crossings
  (``candlescope.pine-bar-path/1``), driven bar by bar by the external Pine clock;
- ``PINE_CHART``: the same path with the chart bar lifecycle and strategy callbacks
  (``candlescope.pine-chart-bar/1``);
- ``PINE_V2``: the chart path with causal V2 account events and shared bar capacity
  (``candlescope.pine-v2-bar/1``).

The clock is part of the run's identity: each path clock keeps its own checkpoint
payload and report-hash contract, unchanged from the kernels it replaces. This module
holds the path machinery as a mixin; the kernel dispatches to it by ``bar_clock``.
"""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, InvalidOperation

from app.market_dataset.snapshot import MarketDatasetError, MarketEvent, sha256_hex
from .account_execution import publish_account_liquidation
from .execution_realism import EXECUTION_REALISM_V2
from .linear_perp_account_v2 import LinearPerpetualAccountV2

BAR_CLOCK = "BAR"
PINE_PATH = "PINE_PATH"
PINE_CHART = "PINE_CHART"
PINE_V2 = "PINE_V2"
BAR_CLOCKS = frozenset({BAR_CLOCK, PINE_PATH, PINE_CHART, PINE_V2})
PATH_CLOCKS = frozenset({PINE_PATH, PINE_CHART, PINE_V2})
CHART_CLOCKS = frozenset({PINE_CHART, PINE_V2})

PATH_CONTRACT = "candlescope.pine-bar-path/1"
PATH_MODEL = "PINE_OHLC_PATH_V1"
CHART_CONTRACT = "candlescope.pine-chart-bar/1"
V2_CONTRACT = "candlescope.pine-v2-bar/1"
LIVE = {"OPEN", "PARTIAL"}
AUXILIARY = {"INSTRUMENT_RULES", "MARK_INDEX", "FUNDING"}
PATH_ACCOUNT_MODELS = {"LINEAR_PERP_ONE_WAY_V1", "SPOT_CASH_V1"}


def crosses_limit(order, price):
    return price <= order.limit_price if order.side == "BUY" else price >= order.limit_price


def triggers_stop(order, price):
    return price >= order.stop_price if order.side == "BUY" else price <= order.stop_price


class OhlcPathClock:
    """Path matching, snapshots and run loops of the Pine bar clocks; mixed into ``SimulationKernel``."""

    __slots__ = ()

    # Identity ------------------------------------------------------------------------------

    def _check_path_clock(self):
        """Path clock limits, checked after the account exists (as the replaced kernels did)."""
        if self.bar_clock in (PINE_PATH, PINE_CHART) and (
                self.execution_model_revision is not None or self.account_model not in PATH_ACCOUNT_MODELS):
            raise MarketDatasetError("Pine BAR path account model unsupported", code="FIDELITY_UNSUPPORTED")
        if self.bar_clock == PINE_V2 and self.execution_model_revision not in {None, EXECUTION_REALISM_V2}:
            raise MarketDatasetError("unknown Pine path execution model", code="FIDELITY_UNSUPPORTED")

    # Matching along the path ---------------------------------------------------------------

    def _path_mark(self, price):
        if not isinstance(self.account, LinearPerpetualAccountV2):
            self.account.mark = price

    def _point(self, price, timestamp, *, vertex, phase="PATH"):
        if self.bar_clock == PINE_V2:
            return self._v2_point(price, timestamp, vertex=vertex, phase=phase)
        self.path_sequence += 1
        event = MarketEvent(self.path_sequence, timestamp, "BARS", {
            **{key: str(price) for key in ("open", "high", "low", "close", "price")},
            "execution_phase": phase, "path_vertex": vertex, "path_contract": PATH_CONTRACT})
        self._last_event = event
        self._market_event_count += 1
        self.account.mark = price
        self._apply_funding(event)
        if self.market_observer is not None:
            self.market_observer(event)
        self._match_point(event, vertex=vertex)
        self.account.mark = price
        self._record_equity(event)
        return event

    def _v2_point(self, price, timestamp, *, vertex, phase="PATH"):
        prototype = MarketEvent(0, timestamp, "BARS", {
            **{key: str(price) for key in ("open", "high", "low", "close", "price")},
            "execution_phase": phase, "path_vertex": vertex, "path_contract": V2_CONTRACT,
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
        self._path_mark(price)
        self._market_event_count += 1
        self._apply_funding(point)
        if self.market_observer is not None:
            self.market_observer(point)
        pending, self._pending_callbacks = self._pending_callbacks, []
        for _receipt in pending:
            self._delivered_account_callbacks.append(_receipt["order_id"])
            self._callback(self._active_bar, point, "order_fill")
        self._match_point(point, vertex=vertex)
        self._path_mark(price)
        self._record_equity(point)
        return point

    def _apply_auxiliary(self, source, point=None):
        if source.role not in AUXILIARY:
            raise MarketDatasetError("unsupported Pine account event", code="FIDELITY_MISLABEL")
        self.path_sequence += 1
        price = (self._last_path_price or Decimal(1)) if point is None else Decimal(point.payload["price"])
        self._last_event = MarketEvent(self.path_sequence, source.event_time_ms, source.role,
            {**source.payload, "price": str(price), "close": str(price), "path_source": self._wire(source),
             "execution_phase": "PATH_AUX", "path_contract": V2_CONTRACT})
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

    def _path_prepare(self, order, event):
        return (order.status in LIVE and (self.order_policy is None or self.order_policy(order, event)))

    def _match_point(self, event, *, vertex, order_ids=None):
        if self.bar_clock == PINE_V2:
            return self._v2_match_point(event, vertex=vertex, order_ids=order_ids)
        price = Decimal(event.payload["price"])
        # Re-read orders after every fill: allocation, OCO, cancellation and
        # callback amendments all operate on the same authoritative account.
        for _ in range(10000):
            progress = False
            for order in tuple(self._live_orders()):
                if order_ids is not None and order.order_id not in order_ids:
                    continue
                if order.eligible_after_sequence > event.sequence or not self._path_prepare(order, event):
                    continue
                if order.type == "STOP_LIMIT" and not order.activated and triggers_stop(order, price):
                    order.activated = True
                limit = order.type == "LIMIT" or (order.type == "STOP_LIMIT" and order.activated)
                if not ((limit and crosses_limit(order, price))
                        or (order.type == "STOP" and triggers_stop(order, price))
                        or (order.type == "MARKET" and vertex)):
                    continue
                fill_price = price
                if not limit:
                    fill_price += price * self.slippage_bps / 10000 * (1 if order.side == "BUY" else -1)
                reason = ("PINE_BAR_CLOSE" if event.payload["execution_phase"] == "PINE_BAR_CLOSE"
                          else "LIMIT_TOUCH" if limit else "STOP_TOUCH" if order.type == "STOP" else
                          "MARKET_OBSERVATION_VERTEX" if order_ids is not None else "MARKET_NEXT_VERTEX")
                self._fill(order, event.sequence, fill_price, reason)
                # _fill publishes synchronously; restore the observation mark
                # even when transaction slippage moved the ledger's mark.
                self.account.mark = price
                progress = True
                break
            if not progress:
                return
        raise MarketDatasetError("Pine BAR matching budget exceeded", code="BUDGET_EXCEEDED")

    def _v2_match_point(self, event, *, vertex, order_ids=None):
        from .v2_margin import reprice
        reprice(self, event)
        price = Decimal(event.payload["price"])
        eligible = []
        for _ in range(10000):
            progress = False
            for order in tuple(self._live_orders()):
                if order_ids is not None and order.order_id not in order_ids:
                    continue
                if order.eligible_after_sequence > event.sequence or not self._path_prepare(order, event):
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
                self._path_mark(price)
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

    def match_observation_markets(self, event):
        """Settle only markets created by this historical vertex observation.

        Price orders and orders created by fill callbacks keep their next-event
        eligibility. V2 still owns margin, partial fills and shared bar capacity.
        """
        if event is not self._last_event or not event.payload.get("path_vertex"):
            raise MarketDatasetError("observation matching requires the current vertex", code="FIDELITY_UNSUPPORTED")
        selected = {order.order_id: order.eligible_after_sequence for order in tuple(self._live_orders())
                    if order.type == "MARKET" and order.eligible_after_sequence == event.sequence+1}
        for order in tuple(self._live_orders()):
            if order.order_id in selected:
                order.eligible_after_sequence = event.sequence
        self._match_point(event, vertex=True, order_ids=set(selected))

    def _levels(self, start, end):
        event = self._last_event
        levels = []
        for order in tuple(self._live_orders()):
            if not self._path_prepare(order, event):
                continue
            if order.type in {"LIMIT", "STOP_LIMIT"} and (order.type == "LIMIT" or order.activated):
                levels.append(order.limit_price)
            elif order.type in {"STOP", "STOP_LIMIT"}:
                levels.append(order.stop_price)
        if self.path_level_provider is not None:
            levels.extend(self.path_level_provider())
        return [level for level in levels if level is not None
                and (start < level <= end if end > start else end <= level < start)]

    def _interleave_point(self, start, finish, begin_ms, end_ms, price, timestamp, endpoint):
        if self.bar_clock == PINE_V2 and self._auxiliary_cursor < len(self._auxiliary):
            stamp = self._auxiliary[self._auxiliary_cursor].event_time_ms
            if stamp < timestamp:
                value = start if end_ms == begin_ms else start + (finish - start) * Decimal(stamp - begin_ms) / (end_ms - begin_ms)
                return value, stamp, False
        return price, timestamp, endpoint

    def walk_bar(self, bar, on_close, *, on_vertex=None):
        """Match four OHLC vertices and continuous price-order crossings.

        Historical script OHLCV is supplied separately by the Host clock.
        Equal-distance bars choose low first as an explicit local policy.
        """
        if self.bar_clock not in PATH_CLOCKS:
            raise MarketDatasetError("the BAR clock has no OHLC path", code="FIDELITY_UNSUPPORTED")
        values = {name: Decimal(str(bar.payload[name])) for name in ("open", "high", "low", "close")}
        if (any(not value.is_finite() or value <= 0 for value in values.values())
                or not values["low"] <= min(values["open"], values["close"])
                <= max(values["open"], values["close"]) <= values["high"]):
            raise MarketDatasetError("invalid OHLC path", code="DATA_QUALITY_FAILED")
        first, second = (("high", "low") if values["high"] - values["open"] < values["open"] - values["low"]
                         else ("low", "high"))
        vertices = [values[name] for name in ("open", first, second, "close")]
        begin, end = int(bar.payload["open_time_ms"]), int(bar.payload["close_time_ms"])
        times = [begin + (end - begin) * index // 3 for index in range(4)]
        point = self._point(vertices[0], times[0], vertex=True)
        if on_vertex is not None:
            on_vertex(point, 0)
        for index in range(1, 4):
            start, finish = vertices[index - 1], vertices[index]
            position = start
            for _ in range(10000):
                levels = self._levels(position, finish)
                next_price = min(levels, key=lambda level: abs(level - position)) if levels else finish
                endpoint = next_price == finish
                timestamp = times[index] if start == finish else times[index - 1] + int(
                    (times[index] - times[index - 1]) * abs(next_price - start) / abs(finish - start))
                next_price, timestamp, endpoint = self._interleave_point(
                    start, finish, times[index - 1], times[index], next_price, timestamp, endpoint)
                point = self._point(next_price, timestamp, vertex=endpoint)
                position = next_price
                if endpoint:
                    if on_vertex is not None:
                        on_vertex(point, index)
                    break
            else:
                raise MarketDatasetError("Pine BAR crossing budget exceeded", code="BUDGET_EXCEEDED")
        on_close(self._last_event)

    def closing_tick(self):
        previous = self._last_event
        return self._point(Decimal(previous.payload["price"]), previous.event_time_ms,
                           vertex=True, phase="PINE_BAR_CLOSE")

    @staticmethod
    def _wire(event):
        return None if event is None else {"sequence": event.sequence, "event_time_ms": event.event_time_ms,
            "role": event.role, "payload": dict(event.payload)}

    # Checkpoints and reports ---------------------------------------------------------------

    def _check_path_snapshot(self):
        if self.bar_clock == PINE_V2 and (self._active_bar is not None or self._failed_bar):
            raise MarketDatasetError("commit the complete Pine V2 bar before snapshot", code="CHECKPOINT_CORRUPT")

    def _path_snapshot(self, state):
        state = {**state, "pine_bar_path": {"contract": PATH_CONTRACT, "sequence": self.path_sequence}}
        if self.bar_clock in CHART_CLOCKS:
            state["pine_chart_bar"] = {"contract": CHART_CONTRACT, "sequence": self.source_sequence,
                "time_ms": self.source_time_ms, "bar_count": self.chart_bar_count}
        if self.bar_clock == PINE_V2:
            state["pine_v2_bar"] = {
                "contract": V2_CONTRACT, "last_bar_close_ms": self._last_bar_close_ms,
                "pending_callbacks": deepcopy(self._pending_callbacks),
                "delivered_account_callbacks": list(self._delivered_account_callbacks),
                "last_path_price": None if self._last_path_price is None else str(self._last_path_price),
                "capacity_left": None if self._capacity_left is None else str(self._capacity_left)}
        return state

    def _restore_path(self, payload):
        if payload.get("pine_v2_bar") is not None and self.bar_clock != PINE_V2:
            raise MarketDatasetError("V2 path snapshot requires its own matcher", code="CHECKPOINT_CORRUPT")
        if payload.get("pine_chart_bar") is not None and self.bar_clock not in CHART_CLOCKS:
            raise MarketDatasetError("chart BAR snapshot requires its own clock", code="CHECKPOINT_CORRUPT")
        state = payload.get("pine_bar_path") or {}
        if (state.get("contract") != PATH_CONTRACT or type(state.get("sequence")) is not int
                or state["sequence"] < 0
                or (payload.get("last_event") or {}).get("sequence", 0) != state["sequence"]):
            raise MarketDatasetError("Pine BAR checkpoint differs", code="CHECKPOINT_CORRUPT")
        self._restore_bar(payload)
        self.path_sequence = state["sequence"]

    def _restore_chart(self, payload):
        state = payload.get("pine_chart_bar") or {}
        if (state.get("contract") != CHART_CONTRACT or type(state.get("sequence")) is not int
                or type(state.get("bar_count")) is not int or state["sequence"] < 0
                or not 0 <= state["bar_count"] <= state["sequence"]
                or (state.get("time_ms") is not None and type(state["time_ms"]) is not int)
                or (state["bar_count"] == 0) != (state.get("time_ms") is None)):
            raise MarketDatasetError("chart BAR checkpoint differs", code="CHECKPOINT_CORRUPT")
        self._restore_path(payload)
        if (self.path_sequence < state["bar_count"] * 4
                or (state["bar_count"] and self._last_event.event_time_ms != state["time_ms"])):
            raise MarketDatasetError("chart BAR path/source clocks differ", code="CHECKPOINT_CORRUPT")
        self.source_sequence, self.source_time_ms, self.chart_bar_count = state["sequence"], state["time_ms"], state["bar_count"]

    def _restore_v2(self, payload):
        state, chart = payload.get("pine_v2_bar") or {}, payload.get("pine_chart_bar") or {}
        if (state.get("contract") != V2_CONTRACT or chart.get("contract") != CHART_CONTRACT
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
        self._restore_path(payload)
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

    def _v2_financial_result(self, fills, ledger):
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
        ledger["pine_v2_path"] = {"contract": V2_CONTRACT, "capacity_left": None if self._capacity_left is None else str(self._capacity_left),
            "pending_account_callbacks": deepcopy(self._pending_callbacks),
            "delivered_account_callbacks": list(self._delivered_account_callbacks)}
        return fills, ledger

    def _path_result(self, result):
        if self.bar_clock == PINE_V2:
            return replace(result, report_hash="sha256:" + sha256_hex({"parent": result.report_hash, "path_contract": V2_CONTRACT}))
        return replace(result, report_hash="sha256:" + sha256_hex({
            "parent": result.report_hash, "path_contract": PATH_CONTRACT, "fill_policy": PATH_MODEL}))

    # Run loops -----------------------------------------------------------------------------

    def _run_chart_clock(self, events, strategy, *, warmup_events=0, finalize=False,
                         checkpoint_callback=None, fill_callback=None, vertex_callback=None, chart_event_callbacks=None, **options):
        if fill_callback is None or warmup_events or options:
            raise MarketDatasetError("chart BAR path requires its explicit callback clock", code="FIDELITY_UNSUPPORTED")
        active = None
        prior_reporter = self.execution_reporter

        prior_observer = self.market_observer
        if chart_event_callbacks is not None:
            def observed(point):
                if 'price' in point.payload:
                    chart_event_callbacks.prepare_path(active,point)
                if prior_observer is not None:prior_observer(point)
            self.market_observer=observed

        def apply(plan, point):
            from .chart_decisions import decision_plans
            for item in decision_plans(plan):
                self._record_decision(item, point)
                self._enqueue_many(item, current_sequence=point.sequence)

        def report(value):
            self.account.mark = Decimal(self._last_event.payload["price"])
            if prior_reporter is not None:
                prior_reporter(value)
            if value.get("fill") and vertex_callback is None:
                trigger = "closing_fill" if self._last_event.payload["execution_phase"] == "PINE_BAR_CLOSE" else "order_fill"
                apply(fill_callback(active, self._last_event, trigger), self._last_event)

        def close(point):
            # The strategy receives canonical OHLCV, with the path close's
            # actual account; the provider observation clock is independent.
            plan=strategy((active,), active)
            if vertex_callback is None or plan: apply(plan,point)
            if self.process_orders_on_close:
                self.closing_tick()

        self.execution_reporter = report
        try:
            for event in events:
                if self.paused:
                    break
                if event.role != "BARS":
                    raise MarketDatasetError("chart BAR path requires bars", code="FIDELITY_MISLABEL")
                if type(event.sequence) is not int or event.sequence <= self.source_sequence:
                    raise MarketDatasetError("chart BAR source sequence went backwards", code="DATA_GAP_REJECTED")
                if event.event_time_ms != int(event.payload["close_time_ms"]):
                    raise MarketDatasetError("chart BAR close timestamp differs", code="DATA_QUALITY_FAILED")
                if self.source_time_ms is not None and (event.event_time_ms < self.source_time_ms
                        or int(event.payload["open_time_ms"]) <= self.source_time_ms):
                    raise MarketDatasetError("chart BAR time went backwards", code="DATA_GAP_REJECTED")
                if self.source_sequence and event.sequence != self.source_sequence + 1:
                    if self.gap_policy == "PAUSE":
                        self.paused = True
                        break
                    if self.gap_policy != "SKIP_WITH_WARNING":
                        raise MarketDatasetError("chart BAR sequence gap", code="DATA_GAP_REJECTED")
                    self.ambiguity_count += 1
                active = event
                self.walk_bar(event, close, on_vertex=(
                    (lambda point,index:apply(chart_event_callbacks.after_path(active,point),point)) if chart_event_callbacks is not None else (
                    (lambda point, index: vertex_callback(active, point, index)) if vertex_callback is not None else None)))
                self.source_sequence, self.source_time_ms = event.sequence, event.event_time_ms
                self.chart_bar_count += 1
                if checkpoint_callback is not None:
                    checkpoint_callback(event)
            if finalize:
                self.finalize_orders()
        finally:
            self.market_observer = prior_observer
            self.execution_reporter = prior_reporter
        return self.result()

    def _run_v2_clock(self, events, strategy, *, warmup_events=0, finalize=False, checkpoint_callback=None, fill_callback=None,
                      vertex_callback=None, chart_event_callbacks=None, **options):
        if fill_callback is None or warmup_events or options or self._failed_bar:
            raise MarketDatasetError("Pine V2 requires its historical callback clock", code="FIDELITY_UNSUPPORTED")
        prior = self.execution_reporter
        checked_sequence, checked_time = self.source_sequence, self.source_time_ms
        pending = []

        prior_observer = self.market_observer
        if chart_event_callbacks is not None:
            def observed(point):
                if 'price' in point.payload:
                    chart_event_callbacks.prepare_path(self._active_bar,point)
                if prior_observer is not None:prior_observer(point)
            self.market_observer=observed

        def apply(plan, point):
            from .chart_decisions import decision_plans
            for item in decision_plans(plan):
                self._record_decision(item, point)
                self._enqueue_many(item, current_sequence=point.sequence)

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
                    (lambda point,index:apply(chart_event_callbacks.after_path(self._active_bar,point),point)) if chart_event_callbacks is not None else (
                    (lambda point, index: vertex_callback(source, point, index)) if vertex_callback is not None else None)))
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
            self.market_observer = prior_observer
            self.execution_reporter, self._callback, self._active_bar, self._observation_point = prior, None, None, None
            self._auxiliary, self._auxiliary_cursor = [], 0
        return self.result()
