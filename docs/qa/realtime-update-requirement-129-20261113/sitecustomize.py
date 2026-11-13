"""QA-only native update witness: one public subscription, bounded scalar tee.

No producer input, source connection, output value or application file is changed.
The caller selects a 10-second ordinary throttle via the existing configuration.
"""
import collections
import functools
import importlib.abc
import importlib.machinery
import json
import logging
import os
import sys
import time

logging.basicConfig(level=logging.WARNING)
DESTINATION = os.environ.get('CANDLESCOPE_QA_UPDATE_WITNESS_FILE')
MODULE = 'app.data_engine.data_manager.manager'
FIELDS = ('time', 'open', 'high', 'low', 'close', 'volume', 'quote_volume',
          'trades', 'taker_buy_base', 'taker_buy_quote')
MAX_ATTEMPTS = 256


def patch(module):
    original_init = module.DataManager.__init__
    @functools.wraps(original_init)
    def initialize(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        publisher = self.bar_aggregator.publisher
        original_emit = publisher.emit_updated
        pending = {}
        count, handle = 0, None

        def write(kind, **values):
            with open(DESTINATION, 'a', encoding='utf-8') as stream:
                stream.write(json.dumps({'pid': os.getpid(), 'kind': kind,
                    'wall_ms': time.time_ns()//1000000, **values}, sort_keys=True)+'\n')

        def fingerprint(key, bar):
            return json.dumps([str(key), [getattr(bar, name) for name in FIELDS]], separators=(',', ':'))

        async def observe(event):
            if event.event_type is not module.DataEventType.BAR_UPDATED or event.bar is None:
                return
            token = fingerprint(event.key, event.bar)
            matches = pending.get(token)
            if matches:
                identifier = matches.popleft()
                if not matches:
                    pending.pop(token)
                write('delivered', attempt=identifier, key=str(event.key))

        async def emit_updated(state):
            nonlocal count, handle
            watched = (self._started and count < MAX_ATTEMPTS and state.exchange == 'okx'
                       and state.market_type == 'spot' and state.symbol == 'BTC-USDT')
            if not watched:
                return await original_emit(state)
            if handle is None:
                handle = self.subscribe(observe, preserve_updates=True, continuity='gap_aware',
                    event_types={module.DataEventType.BAR_UPDATED})
                write('registered', throttle_ms=publisher.snapshot()['update_throttle_ms'],
                      scope='public wildcard read-only subscription; no additional stream lease')
            key = module.SeriesKey(state.symbol, state.interval, exchange=state.exchange,
                market_type=state.market_type, **state.identity.to_dict())
            bar = module.BarData.from_bar_state(state, is_closed=False)
            count += 1
            token = fingerprint(key, bar)
            pending.setdefault(token, collections.deque()).append(count)
            write('attempt', attempt=count, key=str(key), interval=state.interval,
                  values=[getattr(bar, name) for name in FIELDS])
            return await original_emit(state)
        publisher.emit_updated = emit_updated
    module.DataManager.__init__ = initialize


class Loader(importlib.abc.Loader):
    def __init__(self, original):
        self.original = original
    def create_module(self, spec):
        return self.original.create_module(spec)
    def exec_module(self, module):
        self.original.exec_module(module)
        patch(module)
        sys.meta_path.remove(finder)


class Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == MODULE:
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
            if spec is not None:
                spec.loader = Loader(spec.loader)
            return spec
        return None


if DESTINATION:
    with open(DESTINATION, 'a', encoding='utf-8') as stream:
        stream.write(json.dumps({'kind': 'bootstrap', 'pid': os.getpid(),
            'sidecar_main': 'app.desktop_sidecar' in sys.orig_argv})+'\n')
if DESTINATION and 'app.desktop_sidecar' in sys.orig_argv:
    finder = Finder()
    sys.meta_path.insert(0, finder)
