"""Bounded OHLCV range reads over the same frozen BAR input as execution."""

from bisect import bisect_left
from decimal import Decimal, localcontext

from ..display_time import SourceBucketTimeMapper
from ..models import normalize_decimal_string
from app.data_engine.interval_policy import parse_interval_ms


class PreparedDisplay:
    def __init__(self, bars, base_ms, source_revision):
        self.base_ms = base_ms
        self.revision = source_revision
        self.opens = tuple(bar.open_time_ms for bar in bars)
        self.size = 1
        while self.size < len(bars):
            self.size *= 2
        self.nodes = [None] * (2 * self.size)
        for i, bar in enumerate(bars):
            self.nodes[self.size + i] = (
                Decimal(bar.open),
                Decimal(bar.high),
                Decimal(bar.low),
                Decimal(bar.close),
                Decimal(bar.volume),
                None if bar.quote_volume is None else Decimal(bar.quote_volume),
                bar.trades,
                None if bar.taker_buy_base is None else Decimal(bar.taker_buy_base),
                None if bar.taker_buy_quote is None else Decimal(bar.taker_buy_quote),
                1,
                bar.open_time_ms,
                bar.open_time_ms,
                True,
            )
        with localcontext() as context:
            context.prec = 60
            for i in range(self.size - 1, 0, -1):
                self.nodes[i] = self.merge(self.nodes[2 * i], self.nodes[2 * i + 1])

    def merge(self, a, b):
        if a is None:
            return b
        if b is None:
            return a
        sums = tuple(
            None if a[i] is None or b[i] is None else a[i] + b[i] for i in range(4, 9)
        )
        return (
            a[0],
            max(a[1], b[1]),
            min(a[2], b[2]),
            b[3],
            *sums,
            a[9] + b[9],
            a[10],
            b[11],
            a[12] and b[12] and a[11] + self.base_ms == b[10],
        )

    def range(self, start, end):
        left, right = (
            bisect_left(self.opens, start) + self.size,
            bisect_left(self.opens, end) + self.size,
        )
        before = after = None
        with localcontext() as context:
            context.prec = 60
            while left < right:
                if left & 1:
                    before = self.merge(before, self.nodes[left])
                    left += 1
                if right & 1:
                    right -= 1
                    after = self.merge(self.nodes[right], after)
                left //= 2
                right //= 2
            return self.merge(before, after)

    def query(self, revision, display_interval, **kw):
        if revision != self.revision or not self.opens:
            return None
        mapper = SourceBucketTimeMapper.create(
            interval=display_interval,
            actual_replay_start_ms=kw["actual_replay_start_ms"],
            public_replay_start_ms=kw["public_replay_start_ms"],
            source_bucket_anchor_ms=kw.get("source_bucket_anchor_ms"),
        )
        delta = kw["actual_replay_start_ms"] - kw["public_replay_start_ms"]
        end = kw["actual_end_ms"]
        last_bucket = mapper.actual_containing_bucket_open(end - 1)
        ordinal = mapper.actual_bucket_ordinal(last_bucket)
        begin = max(
            kw["actual_start_ms"], mapper.actual_bucket_open(ordinal - kw["limit"] - 2)
        )
        clipped_prefix = begin - delta < self.opens[0]
        if end - delta > self.opens[-1] + self.base_ms:
            return None
        if clipped_prefix:
            begin = self.opens[0] + delta
        first_ordinal = mapper.actual_bucket_ordinal(
            mapper.actual_containing_bucket_open(begin)
        )
        rows = []
        for number in range(first_ordinal, ordinal + 1):
            bucket = mapper.actual_bucket_open(number)
            bucket_end = mapper.actual_bucket_end(bucket)
            if (bucket_end - bucket) % self.base_ms:
                continue
            value = self.range(max(begin, bucket) - delta, min(end, bucket_end) - delta)
            if value is None or not value[12] or value[10] + delta != bucket:
                continue
            expected = (bucket_end - bucket) // self.base_ms
            complete = (
                value[9] == expected and value[11] + delta + self.base_ms == bucket_end
            )
            partial = (
                kw.get("include_partial", False)
                and value[9] < expected
                and value[11] + delta + self.base_ms == end
            )
            if not (complete or partial):
                continue

            def text(value, field, aggregate=False):
                if value is None:
                    return None
                if aggregate:
                    value = Decimal(str(round(float(value), 12)))
                return normalize_decimal_string(format(value, "f"), field_name=field)

            public = mapper.public_from_actual(bucket)
            public_last = min(
                mapper.public_bucket_end(public) - self.base_ms,
                public + (value[9] - 1) * self.base_ms,
                end - delta - 1,
            )
            if public < 0 or public_last < public:
                continue
            rows.append(
                {
                    "open_time_ms": public,
                    "close_time_ms": mapper.public_bucket_end(public) - 1,
                    **{
                        name: text(value[i], name)
                        for i, name in enumerate(("open", "high", "low", "close"))
                    },
                    "volume": text(value[4], "volume", True),
                    "quote_volume": text(value[5], "quote_volume", True),
                    "trades": value[6],
                    "taker_buy_base": text(value[7], "taker_buy_base", True),
                    "taker_buy_quote": text(value[8], "taker_buy_quote", True),
                    "first_base_open_ms": public,
                    "last_base_open_ms": public_last,
                    "component_count": value[9],
                    "expected_components": expected,
                    "is_closed": complete,
                    "synthetic": False,
                }
            )
        if clipped_prefix and len(rows) < kw['limit']:
            return None
        return {
            "bars": rows[-(kw["limit"] + 1) :],
            "has_more": begin > kw["actual_start_ms"] or len(rows) > kw["limit"],
        }


class PreparedDisplayRepository:
    def __init__(self, repository, display):
        self.repository = repository
        self.display = display

    def __getattr__(self, name):
        return getattr(self.repository, name)

    def query_source_bucket_bars_at_revision(
        self, revision, symbol, base_interval, display_interval, **kwargs
    ):
        result = (
            self.display.query(revision, display_interval, **kwargs)
            if parse_interval_ms(base_interval) == self.display.base_ms
            else None
        )
        if result is not None:
            return result
        return self.repository.query_source_bucket_bars_at_revision(
            revision, symbol, base_interval, display_interval, **kwargs
        )
