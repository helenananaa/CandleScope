"""Bounded market-only evaluation for the frozen chart grammar.

Only the host-owned exact ChartPyneStrategyProvider is eligible. Speculative
calculation never advances its live state: matching, traces and checkpoints
consume one result at a time. No user Python is invoked with future data.
"""
from collections import deque
from decimal import Decimal, localcontext
from itertools import islice
import time
import operator
import hashlib

from app.core.config import getenv
from .chart_pyne import ChartPyneStrategyProvider, Operand
from .protocol import ObservationFrame, StrategyProviderError
from .qualified_json import encode_ascii_tree


def compile_condition(provider, condition):
    if condition is None:
        return lambda: True
    value = provider._value
    left, right = condition.left, condition.right
    if condition.kind in {"crossover", "crossunder"}:
        previous_left = Operand(left.name, 1, None)
        previous_right = Operand(right.name, 1, None)
        crossover = condition.kind == "crossover"
        def matches():
            a, b = value(left), value(right)
            c, d = value(previous_left), value(previous_right)
            if a is None or b is None or c is None or d is None:
                return False
            return c <= d and a > b if crossover else c >= d and a < b
    else:
        compare = {"<": operator.lt, ">": operator.gt, "<=": operator.le,
                   ">=": operator.ge, "==": operator.eq, "!=": operator.ne}[condition.kind]
        def matches():
            a, b = value(left), value(right)
            return False if a is None or b is None else compare(a, b)
    return matches


class SeriesWindow:
    """Reuse window membership and RSI deltas without changing sum order.

    Decimal addition is deliberately not replaced by a running sum: rounding
    and trailing-zero spelling are part of existing state and trace hashes.
    Equal extrema retain the earliest value, including its decimal spelling.
    """
    def __init__(self, spec, bars):
        self.spec = spec
        self.length = Decimal(spec.length)
        self.zero, self.one, self.hundred = Decimal(0), Decimal(1), Decimal(100)
        size = spec.length + (spec.function == "rsi")
        self.values = deque((b[spec.field] for b in bars[-size:]), maxlen=size)
        self.gains = self.losses = None
        self.extrema = deque()
        self.index = 0
        if spec.function in {"highest", "lowest"}:
            for value in self.values:
                self._extreme(value)

    def _extreme(self, value):
        self.index += 1
        queue = self.extrema
        highest = self.spec.function == "highest"
        while queue and (queue[-1][1] < value if highest else queue[-1][1] > value):
            queue.pop()
        queue.append((self.index, value))
        while queue[0][0] <= self.index - self.spec.length:
            queue.popleft()

    def push(self, value):
        previous = self.values[-1] if self.values else None
        self.values.append(value)
        function = self.spec.function
        if function in {"highest", "lowest"}:
            self._extreme(value)
        if len(self.values) < self.values.maxlen:
            return None
        if function == "sma":
            return sum(self.values, self.zero) / self.length
        if function in {"highest", "lowest"}:
            return self.extrema[0][1]
        if self.gains is None:
            items = list(self.values)
            changes = [right - left for left, right in zip(items, items[1:])]
            self.gains = deque((max(c, self.zero) for c in changes), maxlen=self.spec.length)
            self.losses = deque((max(-c, self.zero) for c in changes), maxlen=self.spec.length)
        else:
            change = value - previous
            self.gains.append(max(change, self.zero))
            self.losses.append(max(-change, self.zero))
        gains = sum(self.gains, self.zero) / self.length
        losses = sum(self.losses, self.zero) / self.length
        return self.hundred if losses == 0 else self.hundred - self.hundred / (self.one + gains / losses)


def build_chart_batch(provider, session, events, resume_sequence, observed, warmup, *, legacy_plan_only=False):
    from app.backtest.colocated import _GuardedProvider

    if getenv("BACKTEST_CHART_BATCH_ENABLED", "1").strip() != "1":
        return None
    if type(provider) is not _GuardedProvider or type(provider.provider) is not ChartPyneStrategyProvider:
        return None
    if type(events) is not tuple:
        return None
    if sum(spec.length + 1 + ChartBatch.chunk_size for spec in provider.provider._program.series) > 65_536:
        return None
    live = provider.provider
    if (tuple(live._series_history) != tuple(spec.name for spec in live._program.series)
            or any(set(row) != {"open", "high", "low", "close"} for row in live._bars)):
        return None
    # Restrict the fast lane to the ordinary, JSON-safe snapshot wire shape.
    # Exotic mappings/values retain the adapter's original validation path.
    for event in events:
        if event.role != "BARS":
            continue
        if (type(event.sequence) is not int or type(event.event_time_ms) is not int
                or type(event.payload) is not dict
                or any(type(k) is not str or (v is not None and type(v) not in (str, int, bool))
                       for k, v in event.payload.items())):
            return None
    return ChartBatch(provider, session, events, resume_sequence, observed, warmup, legacy_plan_only=legacy_plan_only)


class ChartBatch:
    chunk_size = 128

    def __init__(self, guarded, session, events, resume_sequence, observed, warmup, *, legacy_plan_only=False):
        self.guarded = guarded
        self.live = guarded.provider
        self.session = session
        self.events = (e for e in events if e.sequence > resume_sequence and e.role == "BARS")
        self.queue = deque()
        self.observed = observed
        self.warmup = warmup
        self.timeout = min(guarded.step_timeout, guarded.call_timeout)
        self.legacy_plan_only = legacy_plan_only
        self.windows = {s.name: SeriesWindow(s, self.live._bars) for s in self.live._program.series}
        self.wire_bars = [{k: str(v) for k, v in row.items()} for row in self.live._bars]

    def _state_hash(self):
        # Keys come from the parsed ASCII grammar and fixed OHLC schema;
        # dynamic values are Decimal strings and an exact integer sequence.
        payload = {
            "sequence": self.live._last_sequence,
            "bars": self.wire_bars,
            "series": {key: [None if v is None else str(v) for v in values]
                       for key, values in self.live._series_history.items()},
            "target": None if self.live._last_target is None else str(self.live._last_target),
        }
        return "sha256:" + hashlib.sha256(encode_ascii_tree(payload)).hexdigest()

    def _fill(self):
        scratch = ChartPyneStrategyProvider()
        scratch._program = self.live._program
        scratch._bars = list(self.live._bars)
        scratch._series_history = {k: list(v) for k, v in self.live._series_history.items()}
        branches = [(branch, compile_condition(scratch, branch.condition)) for branch in scratch._program.branches]
        # Decimal flags from a future bar must not leak into current accounting.
        with localcontext():
            for offset, event in enumerate(islice(self.events, self.chunk_size)):
                started = time.monotonic()
                self.guarded.deadline.value = started + self.timeout
                try:
                    row = {name: scratch._decimal(event.payload.get(name), name)
                           for name in ("open", "high", "low", "close")}
                    scratch._bars.append(row)
                    if len(scratch._bars) > scratch._program.max_lookback:
                        scratch._bars.pop(0)
                    for spec in scratch._program.series:
                        history = scratch._series_history[spec.name]
                        history.append(self.windows[spec.name].push(row[spec.field]))
                        if len(history) > 2:
                            history.pop(0)
                    evaluated = []
                    if self.observed + offset >= self.warmup:
                        for branch, matches in branches:
                            matched = matches()
                            evaluated.append((branch, matched))
                            if matched:
                                break
                    record = (scratch._bars[-1], tuple(v[-1] for v in scratch._series_history.values()), evaluated)
                    elapsed = time.monotonic() - started
                    if elapsed > self.timeout:
                        raise StrategyProviderError("PROVIDER_TIMEOUT", "chart batch calculation exceeded step budget")
                    self.queue.append((event, record, elapsed))
                except Exception as exc:
                    # Defer invalid future data to its original decision boundary.
                    self.queue.append((event, exc, time.monotonic() - started))
                    break

    def observe(self, event, phase):
        try:
            if not self.queue:
                self._fill()
            expected, record, calculation_seconds = self.queue.popleft()
            # Calculation and consumption share the original one-step budget.
            self.guarded.deadline.value = time.monotonic() + max(0., self.timeout - calculation_seconds)
            if expected is not event:
                raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "chart batch event order changed")
            # The frozen grammar never reads input_hash, market or features.
            # Do not compute their JSON receipts on this private host-only route.
            frame = ObservationFrame(self.session.run_id, event.sequence, event.event_time_ms,
                                     event.event_time_ms, phase, {}, "", bar=event.payload)
            self.session._accept_frame(frame)
            if isinstance(record, Exception):
                raise record
            row, values, evaluated = record
            live = self.live
            live._bars.append(row)
            if not self.legacy_plan_only:
                self.wire_bars.append({k: str(v) for k, v in row.items()})
            if len(live._bars) > live._program.max_lookback:
                live._bars.pop(0)
                if not self.legacy_plan_only:
                    self.wire_bars.pop(0)
            for history, value in zip(live._series_history.values(), values):
                history.append(value)
                if len(history) > 2:
                    history.pop(0)
            live._last_sequence = event.sequence
            self.observed += 1
            if phase == "WARMUP":
                result = None
            elif self.legacy_plan_only:
                # Private legacy planner input, never a provider wire receipt.
                # This planner only consumes kind/payload; its durable decisions
                # are order intents. Versioned policies retain full output hashes.
                payload = live._decision_payload(frame, evaluated)
                result = None if payload is None else {"kind": "TARGET_POSITION", "payload": payload}
            else:
                result = live._finish_step(frame, evaluated, state_hash=self._state_hash)
            if time.monotonic() > self.guarded.deadline.value:
                raise StrategyProviderError("PROVIDER_TIMEOUT", "chart batch consumption exceeded step budget")
            return result
        finally:
            self.guarded.deadline.value = 0.0
