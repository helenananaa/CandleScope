"""Bounded per-query batching of finer canonical presence probes.

This working index is discarded every 32 targets. It has no process/global
cache, writer or revision owner: the caller pins and fences all source versions
through B130/D126. Probes never qualify a finer row as an accepted component.
"""
from app.data_engine.aggregation.blocks import BlockUnavailable
from app.data_engine.history.cover_plan import plan_fixed_batch
from app.data_engine.history.source_precedence import finer_requirements, collect_presence_windows
from app.data_engine.memory_budget import MemoryBudgetExceeded, retained_size

BATCH_TARGETS = 32
WORK_BYTES = 4 * 1024 * 1024
PLAN_BYTES = 32_768 * 512 + 64 * 1024


class MixedPrecedence:
    def __init__(self, engine, storage, target, sources, precedences, mutations, report):
        self.engine, self.storage, self.target = engine, storage, target
        self.sources, self.precedences, self.mutations = sources, precedences, mutations
        self.report = report
        self.presence = {}

    def _requirements(self, span):
        return finer_requirements(span, self.precedences, self.mutations)

    def prepare(self, opens, width):
        self.presence.clear()
        if not callable(getattr(self.storage, "query_bars_range_presence", None)):
            return
        opens = tuple(opens)
        if not opens:
            return
        with self.engine.memory_budget.reserve("history-query", PLAN_BYTES):
            batch = plan_fixed_batch(self.target, opens[0], opens[-1] + width, self.sources,
                required_fields=self.sources[0].fields, max_targets=len(opens), max_source_rows=131_072)
            self.report["mixed_preflight_positions"] += batch.explored_positions
            requested = collect_presence_windows((span for cover in batch.covers for span in cover.spans),
                                                  self.precedences, self.mutations)
        for source, values in requested.items():
            windows = sorted(values)
            for offset in range(0, len(windows), 256):
                chunk = tuple(windows[offset:offset + 256])
                self.report["mixed_presence_reads"] += 1
                try:
                    flags = self.engine._probe_canonical_history_ranges(self.storage, source, chunk)
                except BlockUnavailable:
                    self.report["mixed_presence_failures"] += 1
                    raise
                self.report["mixed_presence_rows"] += len(flags)
                if len(flags) != len(chunk) or any(type(flag) is not bool for flag in flags):
                    raise BlockUnavailable("canonical presence probe violated its bounded result contract")
                self.presence.update(((source, lo, hi), flag) for (lo, hi), flag in zip(chunk, flags))
                if retained_size((requested, self.presence))[0] > WORK_BYTES:
                    raise MemoryBudgetExceeded("mixed precedence work exceeds its bounded allowance")

    def admits(self, span):
        for fine, lo, hi, deleted in self._requirements(span):
            if deleted:
                return False
            key = fine, lo, hi
            if key in self.presence:
                if self.presence[key]:
                    return False
                continue
            # Refinements not in the initial cover and stores without the
            # optional batch read retain the original one-row bounded probe.
            self.report["mixed_probe_reads"] += 1
            rows = self.engine._read_canonical_history_rows(self.storage, fine, lo, hi, 1)
            self.report["mixed_probe_rows"] += len(rows)
            if rows:
                return False
        return True
