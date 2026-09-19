"""Benchmark-only markers around the actual spawn pickle stream and worker.

The events remain in the original multiprocessing pickle; no extra dump/load,
shared data cache or alternate transport is introduced by this probe.
"""
import json
import time
from pathlib import Path
from types import SimpleNamespace


def _restore_marker(stamps, index):
    stamps[index] = time.perf_counter()


class _Marker:
    def __init__(self, stamps, parent_index, child_index):
        self.stamps, self.parent_index, self.child_index = stamps, parent_index, child_index

    def __reduce__(self):
        self.stamps[self.parent_index] = time.perf_counter()
        return _restore_marker, (self.stamps, self.child_index)


def _restore_events(before, events, after):
    return events


class _Events:
    def __init__(self, events, stamps):
        self.events, self.stamps = events, stamps

    def __reduce__(self):
        return _restore_events, (_Marker(self.stamps, 2, 4), self.events, _Marker(self.stamps, 3, 5))


def _worker(target, args, stamps):
    stamps[6] = time.perf_counter()
    try:
        return target(*args)
    finally:
        stamps[7] = time.perf_counter()


class _Process:
    def __init__(self, process, stamps):
        self.process, self.stamps = process, stamps

    def __getattr__(self, name):
        return getattr(self.process, name)

    def start(self):
        self.stamps[0] = time.perf_counter()
        try:
            return self.process.start()
        finally:
            self.stamps[1] = time.perf_counter()


class _Context:
    def __init__(self, context, stamps):
        self.context, self.stamps = context, stamps

    def __getattr__(self, name):
        return getattr(self.context, name)

    def Process(self, *, target, args, **kwargs):
        args = list(args)
        args[4] = _Events(args[4], self.stamps)
        return _Process(self.context.Process(target=_worker, args=(target, tuple(args), self.stamps), **kwargs), self.stamps)


def install(module, output):
    original_execute, original_mp = module.execute, module.multiprocessing
    context = original_mp.get_context("spawn")

    def execute(*args, **kwargs):
        stamps = context.RawArray("d", 8)
        module.multiprocessing = SimpleNamespace(get_context=lambda method: _Context(context, stamps))
        started = time.perf_counter()
        try:
            return original_execute(*args, **kwargs)
        finally:
            ended = time.perf_counter()
            module.multiprocessing = original_mp
            values = list(stamps)
            def span(a, b):
                return values[b] - values[a] if values[a] and values[b] else None
            data = {
                "kind": "actual-spawn-stream-markers-not-exclusive-cpu-times",
                "execute_seconds": ended-started,
                "process_start_seconds": span(0, 1),
                "parent_event_pickle_seconds": span(2, 3),
                "child_event_unpickle_seconds": span(4, 5),
                "start_to_event_unpickle_seconds": span(0, 4),
                "start_to_worker_entry_seconds": span(0, 6),
                "worker_seconds": span(6, 7),
                "after_worker_seconds": ended-values[7] if values[7] else None,
                "raw_perf_counter": values,
                "scope": "pickle includes stream writes; intervals can overlap across processes; do not sum them",
            }
            Path(output).write_text(json.dumps(data, indent=2), encoding="utf-8")
    module.execute = execute
