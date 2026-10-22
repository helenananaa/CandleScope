"""Observed requested prefixes for one retained indicator subscription."""
from copy import deepcopy

CONTRACT = "candlescope.pine-indicator-observations/1"


def observation_clock(engine, value):
    if value is None:
        return None
    if (not isinstance(value, dict) or set(value) != {"contract", "observedAtMs"}
            or value["contract"] != CONTRACT or type(value["observedAtMs"]) is not int
            or not 0 <= value["observedAtMs"] <= 9_007_199_254_740_991):
        raise ValueError("PINE_REQUEST_DATA_INVALID: exact requested observation contract and clock required")
    capability = getattr(engine, "REALTIME_REQUEST_FEED_SCHEMA_VERSION", None)
    return value["observedAtMs"] if type(capability) is int and capability == 1 else None


def identity(source, options, native_options, observed_at):
    if observed_at is None:
        return deepcopy((source, options, native_options))
    registry = {key: value if key.startswith("$") else []
                for key, value in options.get("request_bars", {}).items()}
    return deepcopy((source, {**options, "request_bars": registry}, CONTRACT))


def requested_rows(options):
    return {key: rows for key, rows in options.get("request_bars", {}).items()
            if not key.startswith("$")}


def immutable_prefix(previous, current):
    return (previous is not None and previous.keys() == current.keys()
            and all(isinstance(rows, (list, tuple))
                    and list(rows[:len(previous[key])]) == previous[key]
                    for key, rows in current.items()))


def chart_cutoff(native, options, bar):
    symbol, timeframe = options.get("chart_symbol"), options.get("chart_timeframe")
    if not symbol or not timeframe:
        raise ValueError("PINE_REQUEST_DATA_INVALID: observed requests require an exact chart context")
    return native.request_bar_close(symbol, timeframe, bar["time"]) - 1


class FeedPlan:
    def __init__(self, native, incoming, previous, observed_at):
        self.cursor = 0
        self.rows = []
        for key, rows in incoming.items():
            if not isinstance(rows, (list, tuple)):
                raise ValueError("PINE_REQUEST_DATA_INVALID: requested rows must be an ordered sequence")
            symbol, timeframe = key.rsplit(":", 1)
            for row in rows[len(previous.get(key, [])):]:
                available = native.request_bar_close(symbol, timeframe, row["time"]) - 1
                if available > observed_at:
                    raise ValueError("PINE_REQUEST_DATA_INVALID: requested row is not yet confirmed at the observation")
                self.rows.append((available, {"symbol": symbol, "timeframe": timeframe,
                    "bar": row, "kind": "confirmed"}))
        self.rows.sort(key=lambda item: item[0])

    def advance(self, native, through):
        end = self.cursor
        while end < len(self.rows) and self.rows[end][0] <= through:
            end += 1
        if end > self.cursor:
            native.apply_request_feed_updates([item[1] for item in self.rows[self.cursor:end]])
            self.cursor = end

    def complete(self):
        if self.cursor != len(self.rows):
            raise ValueError("PINE_REQUEST_DATA_INVALID: requested observation was not consumed")
