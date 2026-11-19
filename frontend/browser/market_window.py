"""Binance spot window for the browser host. Times arrive in milliseconds."""
import json

from app.data_engine.kline_quality import incoming_source_can_replace
from app.data_engine.aggregation.semantics import Coverage, valid_ohlcv
from app.data_engine.data_manager.models import BarData
from app.indicator.indicators.ma import MAIndicator
from app.indicator.indicators.ema import EMAIndicator
from app.indicator.indicators.rsi import RSIIndicator


STUDIES = {"ma": MAIndicator, "ema": EMAIndicator, "rsi": RSIIndicator}


class MarketWindow:
    def __init__(self, width_ms):
        self.width = width_ms
        self.rows = {}
        self.times = []
        self.spans = ()
        self.study_key = None
        self.engines = {}

    def clear(self):
        self.rows.clear()
        self.times = []
        self.spans = ()
        self.study_key = None

    def merge(self, payload, origin):
        changed = []
        old_count = len(self.rows)
        for raw in json.loads(payload):
            opened, *values, closed = raw[:7]
            stream = origin == "stream" or (origin == "cache" and raw[7:8] == ["stream"])
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
                source = "data_manager_exchange_closed" if stream else "backfill"
            previous = self.rows.get(opened)
            if previous and not incoming_source_can_replace(previous[0], source):
                continue
            bar = dict(time=opened // 1000, open=o, high=h, low=l, close=c, volume=v, is_closed=closed)
            if previous != (source, bar):
                self.rows[opened] = (source, bar)
                changed.append(bar)
        # A forming candle updates repeatedly without changing occupancy. Reuse
        # its existing time axis and coverage until a new timestamp appears.
        if old_count != len(self.rows):
            self.times = sorted(self.rows)
            self.spans = Coverage.from_ranges((t, t + self.width, True) for t in self.times).ranges
        gap = (self.spans[0][1], self.spans[1][0]) if len(self.spans) > 1 else None
        return json.dumps(dict(bars=changed, count=len(self.times), gaps=max(0, len(self.spans)-1),
                               gap=gap, first=self.times[0] if self.times else None,
                               last=self.times[-1] if self.times else None))

    def indicators(self, settings, tail_only):
        ordered = self.times
        tail = ordered[-1]
        key = (settings, tail)
        full = not tail_only or key != self.study_key
        lines = {}
        if full:
            self.study_key = key
            self.engines.clear()
            bars = [BarData(**self.rows[t][1]) for t in ordered[:-1]]
            for name, spec in json.loads(settings).items():
                if name not in STUDIES or not spec["enabled"]:
                    continue
                engine = STUDIES[name]({"period": spec["period"], "source": spec["source"]})
                engine.init(bars)
                self.engines[name] = engine
                lines[name] = [
                    {"time": point.timestamp, "value": point.value}
                    for point in engine.get_series(name)[name] if point.value is not None
                ]
        last = BarData(**self.rows[tail][1])
        for name, engine in self.engines.items():
            engine.update_partial(last)
            value = engine.get_preview()[name]
            points = lines.setdefault(name, [])
            if value is not None:
                points.append({"time": last.time, "value": value})
        return json.dumps({"full": full, "lines": lines})
