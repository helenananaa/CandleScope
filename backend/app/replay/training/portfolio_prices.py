"""Immutable market-only integer prices; never caches future account states."""

from bisect import bisect_right
from dataclasses import dataclass
from decimal import Decimal, localcontext

from .multi_interval import ordered_equity_summary


@dataclass(frozen=True)
class PortfolioPrices:
    events: tuple
    times: tuple
    tracks: tuple
    packed: tuple | None
    exponent: int
    largest: int

    @classmethod
    def build(cls, events):
        events = tuple(sorted(events, key=lambda event: event[:4]))
        prices = tuple(event[4] for event in events)
        if any(not price.is_finite() for price in prices):
            raise ValueError("non-finite portfolio market price")
        exponent = min((p.as_tuple().exponent for p in prices), default=0)
        largest = max((p.adjusted() for p in prices), default=0)
        tracks = tuple(sorted({e[2] for e in events}))
        ordinals = {track: i for i, track in enumerate(tracks)}
        # Bound integer construction itself. Exotic market precision retains
        # Decimal events instead of allocating enormous scaled integers.
        packed = None
        if -60 <= exponent <= 60 and largest - exponent + 1 <= 14:
            with localcontext() as context:
                context.prec = 60
                packed = tuple(
                    (e[0], ordinals[e[2]], int(e[4].scaleb(-exponent))) for e in events
                )
        return cls(
            events, tuple(e[0] for e in events), tracks, packed, exponent, largest
        )

    @classmethod
    def from_lanes(cls, lanes):
        return cls.build(
            (
                event.event_time_ms,
                event.event_phase,
                lane.track_id,
                event.event_sequence,
                Decimal(event.payload["mark_price"]),
            )
            for lane in lanes
            if lane.source_kind == "PUBLIC"
            for event in lane.events
            if event.event_kind == "MARK_INDEX" and event.event_phase == 30
        )

    def summary(self, *, cash, legs, initial_prices, start, end, delta=0):
        a, b = bisect_right(self.times, start), bisect_right(self.times, end)
        if end < start:
            raise ValueError("portfolio range is reversed")
        operands = [cash, *initial_prices.values()]
        operands.extend(
            v
            for leg in legs
            for v in (leg.entry, leg.quantity, Decimal(leg.rule.contract_size))
        )
        if any(not value.is_finite() for value in operands):
            raise ValueError("non-finite portfolio account basis")
        smallest = min(self.exponent, *(v.as_tuple().exponent for v in operands))
        largest = max(self.largest, *(v.adjusted() for v in operands))
        if (
            self.packed is None
            or 4 * (largest - smallest + 1) + len(str(len(legs) + 1)) >= 60
        ):
            return ordered_equity_summary(
                cash=cash,
                legs=legs,
                initial_prices=initial_prices,
                events=[(e[0] - delta, *e[1:]) for e in self.events[a:b]],
            )
        with localcontext() as context:
            context.prec = 60
            weights = {track: Decimal(0) for track in initial_prices}
            for leg in legs:
                weights[leg.track_id] += leg.weight
            intercept = cash - sum((leg.entry * leg.weight for leg in legs), Decimal(0))
            price_exponent = min(
                self.exponent, *(p.as_tuple().exponent for p in initial_prices.values())
            )
            value_exponent = min(
                intercept.as_tuple().exponent,
                *(w.as_tuple().exponent + price_exponent for w in weights.values()),
            )
            initial = cash + sum(
                (
                    (initial_prices[leg.track_id] - leg.entry) * leg.weight
                    for leg in legs
                ),
                Decimal(0),
            )
            current = int(initial.scaleb(-value_exponent))
            integer_weights = [
                int(weights[t].scaleb(price_exponent - value_exponent))
                for t in self.tracks
            ]
            previous = [
                int(initial_prices[t].scaleb(-price_exponent)) for t in self.tracks
            ]
            price_multiplier = 10 ** (self.exponent - price_exponent)
            first = peak = trough = current
            drawdown, trough_time = 0, None
            packed = self.packed
            for i in range(a, b):
                timestamp, track, price = packed[i]
                price *= price_multiplier
                current += integer_weights[track] * (price - previous[track])
                previous[track] = price
                if i + 1 < b and packed[i + 1][0] == timestamp:
                    continue
                if current > peak:
                    peak = current
                if current < trough:
                    trough, trough_time = current, timestamp - delta
                drawdown = max(drawdown, peak - current)

            def convert(value):
                return str(Decimal(value).scaleb(value_exponent))

            return dict(
                schema="portfolio-interval-summary.v1",
                first=convert(first),
                last=convert(current),
                peak=convert(peak),
                trough=convert(trough),
                max_drawdown=convert(drawdown),
                trough_time_ms=trough_time,
                events=b - a,
                integer_path=True,
            )
