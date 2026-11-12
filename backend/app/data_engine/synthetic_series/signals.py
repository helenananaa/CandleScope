"""Causal, bounded chart inputs for strategies; no orders, accounts or fills.

Price steps reuse the display transform kernel. ATR is updated from each known
closed source bar, never calibrated from a future loaded window. P&F/Kagi retain
one unfinished column; only reversal confirms that column for close strategies.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import math

from .core import SyntheticConfig, SyntheticError, SyntheticKernel, normalize_source, resolve_options, _round

CONTRACT = 'candlescope.chart-signal-input/1'
ALGORITHM = 'causal-close-source/1'
MAX_SIGNAL_ORDINAL = 2**53 - 1
_FIELDS = {'transform', 'mode', 'box_size', 'min_tick', 'atr_length', 'reversal_amount', 'number_of_lines'}


def normalize_signal_chart(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - (_FIELDS | {'contract', 'algorithm'}):
        raise SyntheticError('invalid chart signal configuration')
    if value.get('contract', CONTRACT) != CONTRACT or value.get('algorithm', ALGORITHM) != ALGORITHM:
        raise SyntheticError('unsupported chart signal contract')
    if isinstance(value.get('atr_length'), bool) or ('atr_length' in value and type(value['atr_length']) is not int):
        raise SyntheticError('atr_length must be an integer')
    try:
        config = SyntheticConfig(**{name: item for name, item in value.items() if name in _FIELDS})
    except (TypeError, ValueError, OverflowError) as exc:
        raise SyntheticError('invalid chart signal configuration') from exc
    return {'contract': CONTRACT, 'algorithm': ALGORITHM,
        **{name: item for name, item in asdict(config).items() if name in _FIELDS}}


class ChartSignalSeries:
    """One private chronological calculation cursor; checkpoints own its state."""
    def __init__(self, definition):
        self.definition = normalize_signal_chart(definition)
        if self.definition is None:
            raise SyntheticError('chart signal definition required')
        self.config = SyntheticConfig(**{name: self.definition[name] for name in _FIELDS})
        self.kernel = SyntheticKernel(self.config)
        self.state = self.kernel._initial()
        self.tick = self.config.min_tick
        self.previous_time = None
        self.previous_close = None
        self.atr_count, self.atr_sum, self.atr = 0, 0.0, 0.0
        self.pending_volume = 0.0
        self.active = None
        self.count = 0
        self.source_count = 0

    def observe(self, payload, available_time_ms):
        previous = self.snapshot()
        try:
            return self._observe(payload, available_time_ms)
        except Exception:
            self.restore(previous)
            raise

    def _observe(self, payload, available_time_ms):
        if type(available_time_ms) is not int or available_time_ms < 0:
            raise SyntheticError('invalid signal availability clock')
        opened = payload.get('open_time_ms')
        closed = payload.get('close_time_ms', available_time_ms)
        if type(opened) is not int or type(closed) is not int or opened > closed or closed > available_time_ms:
            raise SyntheticError('chart signals require an already revealed source close')
        if payload.get('is_closed', True) in (False, 0):
            return []
        row = normalize_source({'time': opened // 1000,
            **{name: payload[name] for name in ('open', 'high', 'low', 'close')},
            'volume': payload.get('volume', 0), 'is_closed': True})
        if self.previous_time is not None and row['time'] <= self.previous_time:
            raise SyntheticError('chart signal source revision/order changed; rebuild the run')
        tr = max(row['high'] - row['low'], abs(row['high'] - self.previous_close) if self.previous_close is not None else 0,
                 abs(row['low'] - self.previous_close) if self.previous_close is not None else 0)
        self.atr_count += 1
        if self.atr_count <= self.config.atr_length:
            self.atr_sum += tr
            self.atr = self.atr_sum / self.atr_count
        else:
            self.atr = (self.atr * (self.config.atr_length - 1) + tr) / self.config.atr_length
        if self.config.transform != 'heikin-ashi':
            if self.tick is None:
                self.tick = resolve_options(self.config, [row])['min_tick']
            options = resolve_options(SyntheticConfig(**{
                **{name: self.definition[name] for name in _FIELDS}, 'mode': 'traditional', 'min_tick': self.tick}), [row])
            if self.config.mode == 'atr' and self.config.transform != 'line-break':
                amount = self.atr or max(self.tick, row['close'] * .005)
                ticks = max(1, _round(amount / self.tick))
                options.update(box_ticks=ticks, box_size=round(ticks * self.tick, 8))
            self.kernel.options = options
        points = self.kernel._step(self.state, row, False)
        self.previous_close, self.previous_time = row['close'], row['time']
        self.source_count += 1
        self.pending_volume += row.get('volume', 0)
        result = []
        if self.config.transform in {'point-and-figure', 'kagi'}:
            if points:
                point = points[0]
                order = point['time']['order']
                if self.active is not None and self.active['time']['order'] != order:
                    result.append(self.active)
                    prior_volume = 0
                else:
                    prior_volume = self.active.get('volume', 0) if self.active else 0
                self.active = {**point, 'volume': prior_volume + self.pending_volume}
                self.pending_volume = 0
        elif points:
            volume = self.pending_volume / len(points)
            result = [{**point, 'volume': volume} for point in points]
            self.pending_volume = 0
        if self.count + len(result) > MAX_SIGNAL_ORDINAL:
            raise SyntheticError('chart signal row budget exceeded')
        emitted = []
        for point in result:
            self.count += 1
            stamp = point['time'] if isinstance(point['time'], (int, float)) else point['time']['sourceTime']
            emitted.append({'ordinal': self.count - 1, 'source_time_ms': int(stamp) * 1000,
                'available_time_ms': available_time_ms, 'source_count': self.source_count,
                'bar': {'open_time_ms': int(stamp) * 1000, 'close_time_ms': available_time_ms,
                    **{name: str(point.get(name, 0)) for name in ('open', 'high', 'low', 'close', 'volume')},
                    'is_closed': True}, 'projection': deepcopy(point)})
        return emitted

    def snapshot(self):
        return {'contract': CONTRACT, 'definition': deepcopy(self.definition), 'math': deepcopy(self.state),
            'tick': self.tick, 'previous_time': self.previous_time, 'previous_close': self.previous_close,
            'atr_count': self.atr_count, 'atr_sum': self.atr_sum, 'atr': self.atr,
            'pending_volume': self.pending_volume, 'active': deepcopy(self.active),
            'count': self.count, 'source_count': self.source_count}

    def restore(self, value):
        if not isinstance(value, dict) or value.get('contract') != CONTRACT or value.get('definition') != self.definition:
            raise SyntheticError('chart signal checkpoint identity changed')
        if type(value.get('count')) is not int or not 0 <= value['count'] <= MAX_SIGNAL_ORDINAL:
            raise SyntheticError('invalid chart signal checkpoint count')
        if (type(value.get('source_count')) is not int or value['source_count'] < 0
                or type(value.get('atr_count')) is not int or value['atr_count'] != value['source_count']
                or not isinstance(value.get('math'), dict)
                or any(not isinstance(value.get(name), (int, float)) or not math.isfinite(value[name])
                       or value[name] < 0 for name in ('atr_sum', 'atr', 'pending_volume'))):
            raise SyntheticError('invalid chart signal checkpoint state')
        for name in ('tick', 'previous_time', 'previous_close', 'atr_count', 'atr_sum', 'atr', 'pending_volume', 'count', 'source_count'):
            setattr(self, name, deepcopy(value[name]))
        self.state, self.active = deepcopy(value['math']), deepcopy(value['active'])
