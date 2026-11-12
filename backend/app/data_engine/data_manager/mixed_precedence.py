"""Bounded per-query batching of finer canonical presence probes.

This working index is discarded every 32 targets. It has no process/global
cache, writer or revision owner: the caller pins and fences all source versions
through B130/D126. Probes never qualify a finer row as an accepted component.
"""
from app.data_engine.aggregation.blocks import BlockUnavailable
from app.data_engine.history.cover_plan import plan_fixed_target
from app.data_engine.memory_budget import MemoryBudgetExceeded, retained_size

BATCH_TARGETS = 32
MAX_PROBES = 4096
WORK_BYTES = 4 * 1024 * 1024
PLAN_BYTES = 32_768 * 512 + 64 * 1024


class MixedPrecedence:
    def __init__(self, engine, storage, target, sources, precedences, mutations, report):
        self.engine, self.storage, self.target = engine, storage, target
        self.sources, self.precedences, self.mutations = sources, precedences, mutations
        self.report = report
        self.presence = {}

    def _requirements(self, span):
        for fine, width in self.precedences:
            if width >= span.source.width_ms:
                continue
            lo, hi = max(0, span.start_ms - width + 1), span.end_ms
            change = self.mutations[fine]
            # The pinned minimum open covers rows and withdrawals. Do not use
            # the close-based upper envelope to skip probes: a malformed finer
            # close may precede its open, including in historical deletions.
            if change is None or change["start_ms"] >= hi:
                continue
            yield fine, lo, hi, change["delete_revision"] > 0

    def prepare(self, opens, width):
        self.presence.clear()
        if not callable(getattr(self.storage, "query_bars_range_presence", None)):
            return
        requested = {}
        count = 0
        with self.engine.memory_budget.reserve("history-query", PLAN_BYTES):
            for opened in opens:
                plan = plan_fixed_target(self.target, opened, opened + width, self.sources,
                                         required_fields=self.sources[0].fields)
                self.report["mixed_preflight_positions"] += plan.explored_positions
                for span in plan.spans:
                    for fine, lo, hi, deleted in self._requirements(span):
                        if deleted or count >= MAX_PROBES:
                            continue
                        bounds = requested.setdefault(fine, set())
                        before = len(bounds)
                        bounds.add((lo, hi))
                        count += len(bounds) - before
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
