"""Bounded Binance spot window for the browser host. Times arrive in milliseconds."""
import json

from kline_quality import incoming_source_can_replace
from semantics import Coverage, valid_ohlcv


class MarketWindow:
    def __init__(self, width_ms):
        self.width = width_ms
        self.rows = {}

    def clear(self):
        self.rows.clear()

    def merge(self, payload, origin):
        changed = []
        for raw in json.loads(payload):
            opened, *values, closed = raw
            if type(opened) is not int or opened < 0 or opened % self.width:
                continue
            prices = tuple(float(value) for value in values)
            if len(prices) != 5 or not valid_ohlcv(prices):
                continue
            o, h, l, c, v = prices
            if not (0 < l <= min(o, c) <= max(o, c) <= h):
                continue
            source = "forming"
            if closed:
                source = "data_manager_exchange_closed" if origin == "stream" else "backfill"
            previous = self.rows.get(opened)
            if previous and not incoming_source_can_replace(previous[0], source):
                continue
            bar = dict(time=opened // 1000, open=o, high=h, low=l, close=c, volume=v, is_closed=closed)
            if previous != (source, bar):
                self.rows[opened] = (source, bar)
                changed.append(bar)
        ordered = sorted(self.rows)
        for expired in ordered[:-2400]:
            del self.rows[expired]
        ordered = ordered[-2400:]
        # Evaluate occupancy separately from the current candle's close state.
        ranges = Coverage.from_ranges((t, t + self.width, self.rows[t][1]["is_closed"]) for t in ordered)
        return json.dumps(dict(bars=changed, count=len(ordered), gaps=max(0, len(ranges.ranges)-1),
                               first=ordered[0] if ordered else None,
                               last=ordered[-1] if ordered else None))
