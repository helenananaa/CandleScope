"""Frozen Pyne requests, with causal Renko observations and real source clocks."""
from datetime import datetime, timezone
from urllib.parse import parse_qsl
import re

import pyne_runtime
from candlescope_plugin_sdk.synthetic_ohlcv import renko_rows


CONTRACT = "source-close-events/1"


def closed_boundary(row, timeframe):
    if row.get("time_close") is not None:
        return int(row["time_close"])
    match = re.fullmatch(r"([1-9][0-9]*)([SmhDWMY]?)", timeframe)
    if not match:
        raise ValueError(f"SYNTHETIC_TIMEFRAME_UNSUPPORTED: {timeframe}")
    count, unit = int(match[1]), match[2]
    stamp = int(row["time"])
    if unit in {"M", "Y"}:
        current = datetime.fromtimestamp(stamp, timezone.utc)
        months = count * (12 if unit == "Y" else 1)
        month = current.year * 12 + current.month - 1 + months
        # Market month bars must start on a month boundary; never silently
        # round an arbitrary imported timestamp into another source period.
        if (current.day, current.hour, current.minute, current.second) != (1, 0, 0, 0):
            raise ValueError("SYNTHETIC_SOURCE_INVALID: calendar source is not aligned")
        return int(datetime(month // 12, month % 12 + 1, 1, tzinfo=timezone.utc).timestamp())
    return stamp + count * {"S": 1, "": 60, "m": 60, "h": 3600,
                            "D": 86400, "W": 604800}[unit]


def market_bars(rows, timeframe):
    return [{**row, "time_close": closed_boundary(row, timeframe)} for row in rows]


class FrozenProvider:
    def __init__(self, contexts, primary=None):
        self.contexts = {(item["symbol"], item["timeframe"]): item["bars"] for item in contexts}
        if primary is not None:
            self.contexts[primary["context"]["symbol"], primary["context"]["timeframe"]] = primary["bars"]
        self.events = {}

    def _rows(self, symbol, timeframe):
        key = (symbol, timeframe)
        if key in self.contexts:
            return self.contexts[key]
        if key in self.events:
            return self.events[key]
        base, separator, query = symbol.partition("?")
        pairs = parse_qsl(query, keep_blank_values=True)
        descriptor = dict(pairs)
        if not separator or descriptor.get("chart") != "renko":
            raise ValueError(f"NATIVE_DATA_MISSING: {symbol}@{timeframe}")
        if len(descriptor) != len(pairs) or set(descriptor) != {"chart", "style", "param"}:
            raise ValueError("SYNTHETIC_INPUT_UNSUPPORTED: freeze explicit unmodified Renko source")
        if getattr(pyne_runtime, "EVENT_REQUEST_SERIES_CONTRACT", None) != CONTRACT:
            raise ValueError("SYNTHETIC_RUNTIME_REQUIRED: install the event-series Pyne runtime")
        source = self.contexts.get((base, timeframe))
        if source is None:
            raise ValueError("SYNTHETIC_SOURCE_REQUIRED: freeze the requested market and timeframe first")
        if len(self.events) >= 16:
            raise ValueError("SYNTHETIC_INPUT_BUDGET: at most 16 synthetic request contexts")
        rows = renko_rows(source, descriptor["style"], descriptor["param"])
        for row in rows:
            row["time_close"] = closed_boundary(source[row["source_index"]], timeframe)
        self.events[key] = rows
        return rows

    def get_ohlcv(self, symbol, timeframe, start, end):
        return [dict(row) for row in self._rows(symbol, timeframe) if start <= row["time"] <= end]

    def get_request_metadata(self, symbol, timeframe):
        self._rows(symbol, timeframe)
        return {"event_series": CONTRACT} if (symbol, timeframe) in self.events else {}
