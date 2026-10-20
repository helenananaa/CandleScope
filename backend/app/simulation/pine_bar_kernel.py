"""Deterministic historical OHLC paths, independent of physical trade tapes."""
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Callable

from app.market_dataset.snapshot import MarketDatasetError, MarketEvent, sha256_hex
from .closing_tick import crosses_limit, triggers_stop
from .kernel import SimulationKernel

CONTRACT = "candlescope.pine-bar-path/1"
MODEL = "PINE_OHLC_PATH_V1"
LIVE = {"OPEN", "PARTIAL"}


@dataclass(slots=True)
class PineBarKernel(SimulationKernel):
    fill_policy: str = MODEL
    path_sequence: int = 0
    path_level_provider: Callable | None = field(default=None, repr=False)

    def __post_init__(self):
        super(PineBarKernel, self).__post_init__()
        if self.execution_model_revision is not None or self.account_model not in {
            "LINEAR_PERP_ONE_WAY_V1", "SPOT_CASH_V1"
        }:
            raise MarketDatasetError("Pine BAR path account model unsupported", code="FIDELITY_UNSUPPORTED")

    def snapshot(self, *, history_encoder=None):
        return {**super(PineBarKernel, self).snapshot(history_encoder=history_encoder),
                "pine_bar_path": {"contract": CONTRACT, "sequence": self.path_sequence}}

    def restore(self, payload):
        state = payload.get("pine_bar_path") or {}
        if (state.get("contract") != CONTRACT or type(state.get("sequence")) is not int
                or state["sequence"] < 0
                or (payload.get("last_event") or {}).get("sequence", 0) != state["sequence"]):
            raise MarketDatasetError("Pine BAR checkpoint differs", code="CHECKPOINT_CORRUPT")
        super(PineBarKernel, self).restore(payload)
        self.path_sequence = state["sequence"]

    def result(self):
        result = super(PineBarKernel, self).result()
        return replace(result, report_hash="sha256:" + sha256_hex({
            "parent": result.report_hash, "path_contract": CONTRACT, "fill_policy": MODEL}))

    def run(self, *args, **kwargs):
        raise MarketDatasetError("Pine BAR path requires its explicit execution clock", code="FIDELITY_UNSUPPORTED")

    def _point(self, price, timestamp, *, vertex, phase="PATH"):
        self.path_sequence += 1
        event = MarketEvent(self.path_sequence, timestamp, "BARS", {
            **{key: str(price) for key in ("open", "high", "low", "close", "price")},
            "execution_phase": phase, "path_vertex": vertex, "path_contract": CONTRACT})
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

    def _prepare(self, order, event):
        return (order.status in LIVE and (self.order_policy is None or self.order_policy(order, event)))

    def _match_point(self, event, *, vertex):
        price = Decimal(event.payload["price"])
        # Re-read orders after every fill: allocation, OCA, cancellation and
        # callback amendments all operate on the same authoritative account.
        for _ in range(10000):
            progress = False
            for order in tuple(self._live_orders()):
                if order.eligible_after_sequence > event.sequence or not self._prepare(order, event):
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
                          else "LIMIT_TOUCH" if limit else "STOP_TOUCH" if order.type == "STOP" else "MARKET_NEXT_VERTEX")
                self._fill(order, event.sequence, fill_price, reason)
                # _fill publishes synchronously; restore the observation mark
                # even when transaction slippage moved the ledger's mark.
                self.account.mark = price
                progress = True
                break
            if not progress:
                return
        raise MarketDatasetError("Pine BAR matching budget exceeded", code="BUDGET_EXCEEDED")

    def _levels(self, start, end):
        event = self._last_event
        levels = []
        for order in tuple(self._live_orders()):
            if not self._prepare(order, event):
                continue
            if order.type in {"LIMIT", "STOP_LIMIT"} and (order.type == "LIMIT" or order.activated):
                levels.append(order.limit_price)
            elif order.type in {"STOP", "STOP_LIMIT"}:
                levels.append(order.stop_price)
        if self.path_level_provider is not None:
            levels.extend(self.path_level_provider())
        return [level for level in levels if level is not None
                and (start < level <= end if end > start else end <= level < start)]

    def walk_bar(self, bar, on_close):
        """Match four OHLC vertices and continuous price-order crossings.

        Historical script OHLCV is supplied separately by the Host clock.
        Equal-distance bars choose low first as an explicit local policy.
        """
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
        self._point(vertices[0], times[0], vertex=True)
        for index in range(1, 4):
            start, finish = vertices[index - 1], vertices[index]
            position = start
            for _ in range(10000):
                levels = self._levels(position, finish)
                next_price = min(levels, key=lambda level: abs(level - position)) if levels else finish
                endpoint = next_price == finish
                timestamp = times[index] if start == finish else times[index - 1] + int(
                    (times[index] - times[index - 1]) * abs(next_price - start) / abs(finish - start))
                self._point(next_price, timestamp, vertex=endpoint)
                position = next_price
                if endpoint:
                    break
            else:
                raise MarketDatasetError("Pine BAR crossing budget exceeded", code="BUDGET_EXCEEDED")
        on_close(self._last_event)

    def closing_tick(self):
        previous = self._last_event
        return self._point(Decimal(previous.payload["price"]), previous.event_time_ms,
                           vertex=True, phase="PINE_BAR_CLOSE")
