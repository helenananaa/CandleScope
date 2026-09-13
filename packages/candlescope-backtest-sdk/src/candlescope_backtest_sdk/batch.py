"""Additive, column-oriented market batch contract for causal strategies.

The host supplies past context plus new rows. A target at index i may depend
only on rows through context_rows+i. Account/execution feedback is excluded.
Hosts must qualify implementations; declaring this contract proves no purity.
"""
from dataclasses import dataclass
from typing import Mapping

MARKET_BATCH_PROTOCOL = "candlescope.python-market-batch/1"
MARKET_BATCH_RECEIPT = "candlescope.python-market-batch-receipt/1"
BAR_COLUMNS = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True, slots=True)
class MarketBatch:
    sequence: tuple[int, ...]
    event_time_ms: tuple[int, ...]
    open: tuple[str, ...]
    high: tuple[str, ...]
    low: tuple[str, ...]
    close: tuple[str, ...]
    volume: tuple[str, ...]
    context_rows: int
    warmup_rows: int

    @classmethod
    def from_columns(cls, columns: Mapping, *, context_rows: int = 0, warmup_rows: int = 0):
        from .models import _decimal_string
        from .contract import MAX_SAFE_INTEGER
        names = ("sequence", "event_time_ms", *BAR_COLUMNS)
        if set(columns) != set(names):
            raise ValueError("market batch columns do not match contract")
        size = len(columns["close"])
        if any(len(columns[name]) != size for name in names):
            raise ValueError("market batch columns must have equal lengths")
        if (type(context_rows) is not int or type(warmup_rows) is not int
                or not 0 <= context_rows <= size or not 0 <= warmup_rows <= size - context_rows):
            raise ValueError("invalid market batch context/warmup range")
        values = {}
        for name in ("sequence", "event_time_ms"):
            value = tuple(columns[name])
            if any(type(v) is not int or abs(v) > MAX_SAFE_INTEGER for v in value):
                raise ValueError("market batch clocks must be interoperable integers")
            if any(b < a or (name == "sequence" and b == a) for a, b in zip(value, value[1:])):
                raise ValueError("market batch clocks must increase")
            values[name] = value
        for name in BAR_COLUMNS:
            values[name] = tuple(_decimal_string(v, f"bar.{name}") for v in columns[name])
        return cls(**values, context_rows=context_rows, warmup_rows=warmup_rows)

    def to_wire(self):
        return {"protocol": MARKET_BATCH_PROTOCOL, "contextRows": self.context_rows,
                "warmupRows": self.warmup_rows, "columns": {
                    name: list(getattr(self, name)) for name in ("sequence", "event_time_ms", *BAR_COLUMNS)}}


def market_batch_hashes(batch: MarketBatch, targets, parameters: Mapping):
    """Reproduce a batch receipt's input/output hashes from retained source data."""
    from .json_codec import canonical_sha256
    if len(targets) != len(batch.sequence) - batch.context_rows:
        raise ValueError("market batch output length mismatch")
    return {
        "inputHash": canonical_sha256({**batch.to_wire(), "parameters": dict(parameters)}),
        "outputHash": canonical_sha256({"protocol": MARKET_BATCH_PROTOCOL, "targets": targets}),
    }
