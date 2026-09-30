"""Binance USD-M native candle openings, separate from synthetic epoch bars."""
from app.data_engine.history.calendar import AlwaysOpenCalendar
from app.data_engine.history.models import TimeRange


class BinanceFuturesCalendar(AlwaysOpenCalendar):
    # Public /fapi/v1/klines observations (BTCUSDT, ETHUSDT, BNBUSDT):
    # 2023-08-14 is followed by 2023-08-16, then every three days.
    # Keep the historical regimes explicit; never learn completeness from the
    # rows being checked, which would hide a real missing candle.
    TRANSITION = 1_692_144_000_000
    WIDTH = 259_200_000
    OLD_PHASE = 172_800_000
    NEW_PHASE = 86_400_000

    def __init__(self):
        super().__init__("binance.usdm.native.utc.v1")

    def first_expected_open(self, start_ms, end_ms, interval):
        if interval != "3d":
            return super().first_expected_open(start_ms, end_ms, interval)
        for lower, upper, phase in (
            (start_ms, min(end_ms, self.TRANSITION - 1), self.OLD_PHASE),
            (max(start_ms, self.TRANSITION), end_ms, self.NEW_PHASE),
        ):
            value = -((phase - lower) // self.WIDTH) * self.WIDTH + phase
            if lower <= value <= upper:
                return value
        return None

    def last_expected_open(self, start_ms, end_ms, interval):
        if interval != "3d":
            return super().last_expected_open(start_ms, end_ms, interval)
        for lower, upper, phase in (
            (max(start_ms, self.TRANSITION), end_ms, self.NEW_PHASE),
            (start_ms, min(end_ms, self.TRANSITION - 1), self.OLD_PHASE),
        ):
            value = ((upper - phase) // self.WIDTH) * self.WIDTH + phase
            if lower <= value <= upper:
                return value
        return None

    def next_expected_open(self, open_ms, interval):
        if interval != "3d":
            return super().next_expected_open(open_ms, interval)
        return self.first_expected_open(open_ms + 1, open_ms + self.WIDTH, interval)

    def previous_expected_open(self, open_ms, interval):
        if interval != "3d":
            return super().previous_expected_open(open_ms, interval)
        return self.last_expected_open(open_ms - self.WIDTH, open_ms - 1, interval)

    def expected_opens(self, start_ms, end_ms, interval):
        current = self.first_expected_open(start_ms, end_ms, interval)
        while current is not None and current <= end_ms:
            yield current
            current = self.next_expected_open(current, interval)

    def count_expected(self, start_ms, end_ms, interval):
        if interval != "3d":
            return super().count_expected(start_ms, end_ms, interval)
        return sum(1 for _ in self.expected_opens(start_ms, end_ms, interval))

    def open_segments(self, start_ms, end_ms, interval):
        first = self.first_expected_open(start_ms, end_ms, interval)
        last = self.last_expected_open(start_ms, end_ms, interval)
        return () if first is None or last is None else (TimeRange(first, last),)
