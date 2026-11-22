"""The Host bar kernel's PRACTICE clock (ADR-BACKTEST-015 P6e3).

Forward runs and practice accounts share one account model, the practice rules (O3). On
this clock the Host kernel does not re-implement those rules: it admits orders as a
practice account does, and each bar's matching is the practice account model itself
(``practice_account``): the same candle cursor, path, triggers, prices, fees and
cancellations. The kernel only books the results into its own ledger, which stays
separate from any practice account's ledger.

A strategy decides at a bar's close, so its market orders (and marketable limits) fill at
that close, as a practice order placed then fills at the current price. Resting orders
match the next bar along the practice path, starting from the previous close. Positions
are one-way (a strategy's intents carry no hedge leg); spot cannot sell more than it holds.
"""
from __future__ import annotations

from decimal import Decimal

from app.market_dataset.snapshot import MarketDatasetError
from .practice_account import (
    BPS, Cursor, PracticeMatcher, PracticeSettings, WorkingOrder, advance_cursor, initial_margin, market_leverage,
)
from .spot_cash_account import SpotCashAccount, reject_spot_fill

PRACTICE = "PRACTICE"
PRACTICE_CONTRACT = "candlescope.practice-path/1"
PRACTICE_FILL_POLICY = "PRACTICE_CANDLE_PATH_V1"
PRACTICE_ACCOUNT_MODELS = {"LINEAR_PERP_ONE_WAY_V1", "SPOT_CASH_V1"}
ORDER_TYPES = {"MARKET", "LIMIT", "STOP"}
# A practice cancellation reason, as the Host order status it ends in.
CANCELLED_STATUS = {"oco_sibling_filled": "CANCELLED_OCO", "position_closed": "CANCELLED_REDUCE_ONLY",
                    "nothing_to_reduce": "CANCELLED_REDUCE_ONLY"}
FILL_REASON = {"market": "PRACTICE_MARKET", "limit": "PRACTICE_LIMIT", "stop": "PRACTICE_STOP"}


def _no_new_orders() -> str:
    raise MarketDatasetError("Host intents carry no practice brackets", code="FIDELITY_UNSUPPORTED")


class PracticeClock:
    """Admission, matching and checkpoints of the PRACTICE clock; mixed into ``SimulationKernel``."""

    __slots__ = ()

    # Identity ------------------------------------------------------------------------------

    def _check_practice_clock(self):
        if self.bar_clock != PRACTICE:
            return
        if (self.account_model not in PRACTICE_ACCOUNT_MODELS or self.execution_model_revision is not None
                or self.funding_mode != "OFF" or self.funding_rate != 0 or self.process_orders_on_close
                or self.leverage <= 0):
            raise MarketDatasetError(
                "the practice account model is one-way perpetual or spot, without funding or closing ticks",
                code="FIDELITY_UNSUPPORTED")

    def _practice_settings(self) -> PracticeSettings:
        return PracticeSettings(taker_fee_rate=self.taker_fee_bps / BPS, maker_fee_rate=self.maker_fee_bps / BPS,
                                slippage_bps=self.slippage_bps, allow_short=not self._practice_spot())

    def _practice_spot(self) -> bool:
        return isinstance(self.account, SpotCashAccount)

    def _practice_leverage(self) -> Decimal:
        return market_leverage(self.leverage, "spot" if self._practice_spot() else "futures")

    # Matching ------------------------------------------------------------------------------

    def _practice_session(self) -> PracticeMatcher:
        orders = [WorkingOrder(id=order.order_id, side=order.side.lower(), type=order.type.lower(), qty=order.qty,
                               created_at_ms=self._practice_created[order.order_id], limit_price=order.limit_price,
                               stop_price=order.stop_price, reduce_only=order.reduce_only, oco_group=order.oco_group)
                  for order in self._live_orders()]
        return PracticeMatcher(orders, self.account.position_qty, self._practice_settings(), new_order_id=_no_new_orders)

    def _practice_walk(self, event) -> None:
        """Match the working orders along the practice path to this bar's close."""
        payload = event.payload
        values = {key: Decimal(str(payload[key])) for key in ("open", "high", "low", "close")}
        bar_time = int(payload["open_time_ms"]) // 1000 if "open_time_ms" in payload else event.event_time_ms // 60_000 * 60
        if self._practice_cursor is None:
            self._practice_cursor = Cursor(bar_time=bar_time, seen_high=values["high"], seen_low=values["low"],
                                           last_close=values["close"], observed_ms=event.event_time_ms)
            return
        cursor, chunk = advance_cursor(self._practice_cursor, bar_time, values["open"], values["high"], values["low"],
                                       values["close"], observed_ms=event.event_time_ms)
        self._practice_cursor = cursor
        if chunk is None or not any(True for _ in self._live_orders()):
            return
        session = self._practice_session()
        session.run(chunk)
        self._apply_practice(session, event.sequence)

    def _apply_practice(self, session: PracticeMatcher, sequence: int) -> None:
        orders = {order.order_id: order for order in self._live_orders()}
        for fill in session.result.fills:
            self._book_practice_fill(orders[fill.order_id], fill, sequence)
        for order_id, (reason, _ts_ms) in session.result.cancelled.items():
            order = orders[order_id]
            if order.status not in {"OPEN", "PARTIAL"}:
                continue
            order.status = CANCELLED_STATUS.get(reason, "CANCELLED")
            self._active_orders.pop(order_id, None)
            self._lifecycle(order, order.status, reason=reason.upper())

    def _book_practice_fill(self, order, fill, sequence: int) -> None:
        """Book one fill the practice model made, at its price, fee and time, into the Host ledger."""
        from .kernel import SimulatedFill, _fill_action

        if self._practice_spot():
            rejection = self.account.fill_rejection(side=order.side, price=fill.price, qty=fill.qty, fee=fill.fee)
            if rejection:
                reject_spot_fill(self, order, sequence, rejection)
                return
        order.status = "FILLED"
        order.fill_price, order.fill_sequence = fill.price, sequence
        self._active_orders.pop(order.order_id, None)
        self.fee_total += fill.fee
        if not self._practice_spot():
            self.account.mark = fill.price
        position_before = self.account.position_qty
        self.account.apply_fill(side=order.side, price=fill.price, qty=fill.qty, fee=fill.fee)
        position_after = self.account.position_qty
        record = SimulatedFill(order_id=order.order_id, sequence=sequence, event_time_ms=fill.ts_ms, side=order.side,
                               price=fill.price, qty=fill.qty, fee=fill.fee, reason=FILL_REASON[order.type.lower()],
                               action=_fill_action(position_before, position_after), position_before=position_before,
                               position_after=position_after, contract_multiplier=Decimal(1))
        self.fills.append(record)
        if self.execution_reporter is not None:
            self.execution_reporter({"accepted": True, "fill": {**self._record_encoder(record), "side": order.side},
                                     "order_id": order.order_id})

    # Admission -----------------------------------------------------------------------------

    def _practice_refusal(self, intent, reference: Decimal) -> str | None:
        """The practice account's order checks, in its order, as a Host rejection reason."""
        kind, side = str(intent.get("type") or ""), str(intent.get("side") or "")
        if kind not in ORDER_TYPES or side not in {"BUY", "SELL"}:
            return "ORDER_TYPE_UNSUPPORTED"
        try:
            qty = Decimal(str(intent.get("qty")))
            limit = None if intent.get("limit_price") is None else Decimal(str(intent["limit_price"]))
            stop = None if intent.get("stop_price") is None else Decimal(str(intent["stop_price"]))
        except ArithmeticError:
            return "INVALID_ORDER"
        if (not qty.is_finite() or qty <= 0 or (kind == "LIMIT" and (limit is None or limit <= 0))
                or (kind == "STOP" and (stop is None or stop <= 0))):
            return "INVALID_ORDER"
        if kind == "STOP" and ((side == "BUY" and stop <= reference) or (side == "SELL" and stop >= reference)):
            return "STOP_WOULD_TRIGGER"
        position = self.account.position_qty
        direction = Decimal(1) if side == "BUY" else Decimal(-1)
        reduce_only = bool(intent.get("reduce_only") or False)
        if reduce_only and (position == 0 or (position > 0) == (direction > 0)):
            return "NOTHING_TO_REDUCE"
        if not reduce_only and self._practice_spot() and side == "SELL" and position - qty < 0:
            return "INSUFFICIENT_POSITION"
        if not reduce_only and (position == 0 or (position > 0) == (direction > 0)):
            entry = {"MARKET": reference, "LIMIT": limit, "STOP": stop}[kind] or reference
            leverage = self._practice_leverage()
            available = self.account.equity() - initial_margin(abs(position), reference, leverage)
            if initial_margin(qty, entry, leverage) > available:
                return "INSUFFICIENT_BALANCE"
        return None

    def _practice_enqueue(self, intent, *, current_sequence: int) -> None:
        from .kernel import SimulatedOrder, _wire_order

        event = self._last_event
        reference = Decimal(str(event.payload["close"]))
        reason = self._practice_refusal(intent, reference)
        if reason is not None:
            rejected = {"accepted": False, "reason": reason, "sequence": current_sequence, "intent": dict(intent)}
            self.rejected.append(rejected)
            self._rejected_lifecycle(rejected)
            if self.execution_reporter is not None:
                self.execution_reporter(rejected)
            return
        order = SimulatedOrder(order_id=f"ord-{self._next_order_id}", side=str(intent["side"]), type=str(intent["type"]),
                               qty=Decimal(str(intent["qty"])),
                               limit_price=None if intent.get("limit_price") is None else Decimal(str(intent["limit_price"])),
                               stop_price=None if intent.get("stop_price") is None else Decimal(str(intent["stop_price"])),
                               eligible_after_sequence=current_sequence + 1,
                               oco_group=str(intent["oco_group"]) if str(intent.get("oco_group") or "").strip() else None,
                               reduce_only=bool(intent.get("reduce_only") or False))
        self.orders.append(order)
        self._active_orders[order.order_id] = order
        self._active_count = len(self.orders)
        self._practice_created[order.order_id] = event.event_time_ms
        self._lifecycle(order, "NEW")
        if self.execution_reporter is not None:
            self.execution_reporter({"accepted": True, "sequence": current_sequence, "order": _wire_order(order),
                                     **({"client_tag": intent["client_tag"]} if "client_tag" in intent else {})})
        self._lifecycle(order, "ACCEPTED")
        self._lifecycle(order, "OPEN")
        self._next_order_id += 1
        # A market order, or a limit already through the price, fills now at the close it was decided on.
        marketable = order.type == "MARKET" or (order.type == "LIMIT" and (
            (order.side == "BUY" and order.limit_price >= reference) or (order.side == "SELL" and order.limit_price <= reference)))
        if marketable:
            session = self._practice_session()
            working = next(item for item in session.working() if item.id == order.order_id)
            session.execute(working, reference, event.event_time_ms, liquidity="taker")
            self._apply_practice(session, event.sequence)

    # Run loop, checkpoints and reports -----------------------------------------------------

    def _run_practice(self, events, strategy, *, warmup_events, finalize, checkpoint_callback, finish_batch=True):
        from .chart_decisions import decision_plans

        for event in events:
            if self.paused:
                break
            if not self._accept_event(event):
                continue
            if event.role != "BARS":
                raise MarketDatasetError("the practice clock matches bars", code="FIDELITY_MISLABEL")
            self._market_event_count += 1
            self._practice_walk(event)
            self.account.mark = Decimal(str(event.payload["close"]))
            intents = strategy((event,), event)
            if self._market_event_count <= warmup_events:
                intents = []
            for plan in decision_plans(intents):
                self._record_decision(plan, event)
                self._enqueue_many(plan, current_sequence=event.sequence)
            self.account.mark = Decimal(str(event.payload["close"]))
            self._record_equity(event)
            if checkpoint_callback is not None:
                checkpoint_callback(event)
        if finish_batch:
            self._append_terminal_curve_point()
            if finalize:
                self.finalize_orders()

    def _practice_snapshot(self, state: dict) -> dict:
        cursor = self._practice_cursor
        return {**state, "practice_path": {
            "contract": PRACTICE_CONTRACT,
            "cursor": None if cursor is None else {
                "bar_time": cursor.bar_time, "seen_high": str(cursor.seen_high), "seen_low": str(cursor.seen_low),
                "last_close": str(cursor.last_close), "observed_ms": cursor.observed_ms, "closes_only": cursor.closes_only},
            "created_ms": dict(self._practice_created)}}

    def _restore_practice(self, payload) -> None:
        state = payload.get("practice_path") or {}
        cursor = state.get("cursor")
        if (state.get("contract") != PRACTICE_CONTRACT or not isinstance(state.get("created_ms"), dict)
                or (cursor is not None and not isinstance(cursor, dict))):
            raise MarketDatasetError("practice path checkpoint differs", code="CHECKPOINT_CORRUPT")
        self._restore_bar(payload)
        try:
            self._practice_cursor = None if cursor is None else Cursor(
                bar_time=int(cursor["bar_time"]), seen_high=Decimal(cursor["seen_high"]), seen_low=Decimal(cursor["seen_low"]),
                last_close=Decimal(cursor["last_close"]), observed_ms=int(cursor["observed_ms"]),
                closes_only=bool(cursor["closes_only"]))
            self._practice_created = {str(key): int(value) for key, value in state["created_ms"].items()}
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            raise MarketDatasetError("practice path checkpoint differs", code="CHECKPOINT_CORRUPT") from exc
        if any(order.order_id not in self._practice_created for order in self._live_orders()):
            raise MarketDatasetError("practice order times differ", code="CHECKPOINT_CORRUPT")
